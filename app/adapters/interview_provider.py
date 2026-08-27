from __future__ import annotations

import json
import logging
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)


class InterviewProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(min_length=1, max_length=100)
    evidence: str = Field(min_length=1, max_length=1000)


class AnalysisSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2000)
    skills: list[str]
    experience: list[str]
    risks: list[str]


class InterviewAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: AnalysisSections
    citations: list[Citation]

    @model_validator(mode="after")
    def require_sections(self) -> InterviewAnalysisResult:
        return self


class QuestionSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(min_length=1, max_length=100)
    chunk_id: UUID | None
    document_id: UUID | None
    evidence: str | None = Field(max_length=1000)


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1, le=10)
    text: str = Field(min_length=1, max_length=2000)
    type: str = Field(min_length=1, max_length=100)
    required: bool
    source_refs: list[QuestionSourceRef]
    evaluation_focus: list[str] = Field(min_length=1)


class InterviewQuestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[GeneratedQuestion]

    def validate_count(self, question_count: int) -> InterviewQuestionResult:
        if len(self.questions) != question_count:
            raise ValueError("question count does not match request")
        if [item.sequence for item in self.questions] != list(range(1, question_count + 1)):
            raise ValueError("question sequence must be contiguous")
        return self


class InterviewProvider(Protocol):
    def analyze_document(self, extracted_text: str) -> InterviewAnalysisResult: ...

    def generate_questions(
        self,
        analysis: dict[str, Any],
        conditions: dict[str, Any],
        question_count: int,
    ) -> InterviewQuestionResult: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    _endpoint = "https://api.openai.com/v1/embeddings"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
        dimensions: int = 3072,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._dimensions = dimensions

    @staticmethod
    def parse_embeddings(payload: str, expected_count: int) -> list[list[float]]:
        try:
            data = json.loads(payload)["data"]
            ordered = sorted(data, key=lambda item: item["index"])
            vectors = [[float(value) for value in item["embedding"]] for item in ordered]
            if len(vectors) != expected_count or any(not vector for vector in vectors):
                raise ValueError("embedding count or dimension mismatch")
            if [int(item["index"]) for item in ordered] != list(range(expected_count)):
                raise ValueError("embedding indexes are not contiguous")
            return vectors
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise InterviewProviderError(
                "INTERVIEW_EMBEDDING_SCHEMA_INVALID", retryable=False
            ) from error

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = json.dumps(
            {
                "model": self._model,
                "input": texts,
                "encoding_format": "float",
                "dimensions": self._dimensions,
            },
            ensure_ascii=False,
        ).encode()
        request = Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                payload = response.read().decode()
        except HTTPError as error:
            raise InterviewProviderError(
                "INTERVIEW_EMBEDDING_UNAVAILABLE",
                retryable=error.code == 429 or error.code >= 500,
            ) from error
        except (URLError, TimeoutError, ValueError) as error:
            raise InterviewProviderError(
                "INTERVIEW_EMBEDDING_UNAVAILABLE", retryable=True
            ) from error
        vectors = self.parse_embeddings(payload, len(texts))
        if any(len(vector) != self._dimensions for vector in vectors):
            raise InterviewProviderError("INTERVIEW_EMBEDDING_SCHEMA_INVALID", retryable=False)
        return vectors


class OpenAIInterviewProvider:
    _endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 120) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def parse_analysis(payload: str) -> InterviewAnalysisResult:
        try:
            return InterviewAnalysisResult.model_validate_json(payload)
        except (ValidationError, ValueError) as error:
            raise InterviewProviderError(
                "INTERVIEW_PROVIDER_SCHEMA_INVALID", retryable=False
            ) from error

    @staticmethod
    def parse_questions(
        payload: str,
        question_count: int,
        allowed_chunk_ids: set[UUID] | None = None,
    ) -> InterviewQuestionResult:
        try:
            parsed = InterviewQuestionResult.model_validate_json(payload)
            parsed.validate_count(question_count)
            if allowed_chunk_ids is not None and any(
                source.chunk_id not in allowed_chunk_ids
                for question in parsed.questions
                for source in question.source_refs
            ):
                raise ValueError("question references evidence outside retrieval result")
            return parsed
        except (ValidationError, ValueError) as error:
            raise InterviewProviderError(
                "INTERVIEW_PROVIDER_SCHEMA_INVALID", retryable=False
            ) from error

    def analyze_document(self, extracted_text: str) -> InterviewAnalysisResult:
        output = self._create_response(
            instructions=(
                "지원 문서를 면접 준비용으로 분석하세요. 제공된 문서에 있는 사실만 사용하고 "
                "각 근거를 짧게 인용하세요. 출력은 지정된 JSON schema를 따르세요."
            ),
            input_text=extracted_text,
            name="interview_document_analysis",
            schema=InterviewAnalysisResult.model_json_schema(),
        )
        return self.parse_analysis(output)

    def generate_questions(
        self,
        analysis: dict[str, Any],
        conditions: dict[str, Any],
        question_count: int,
    ) -> InterviewQuestionResult:
        output = self._create_response(
            instructions=(
                f"면접 질문을 정확히 {question_count}개 생성하세요. sequence는 1부터 연속이고 "
                "각 질문은 제공된 evidence 내용만 근거로 삼아야 합니다. source_refs의 chunk_id는 "
                "반드시 제공된 evidence의 chunk_id 중 하나를 그대로 사용하세요. "
                "각 질문에는 평가 초점도 포함하세요."
            ),
            input_text=json.dumps(
                {"analysis": analysis, "conditions": conditions},
                ensure_ascii=False,
                default=str,
            ),
            name="interview_question_generation",
            schema=InterviewQuestionResult.model_json_schema(),
        )
        chunk_ids = {
            UUID(str(chunk["chunk_id"]))
            for chunk in analysis.get("evidence", [])
            if chunk.get("chunk_id")
        }
        return self.parse_questions(output, question_count, allowed_chunk_ids=chunk_ids)

    def _create_response(
        self,
        *,
        instructions: str,
        input_text: str,
        name: str,
        schema: dict[str, Any],
    ) -> str:
        body = json.dumps(
            {
                "model": self._model,
                "instructions": instructions,
                "input": input_text,
                "store": False,
                "reasoning": {"effort": "low"},
                "max_output_tokens": 2000,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": name,
                        "strict": True,
                        "schema": schema,
                    }
                },
            },
            ensure_ascii=False,
        ).encode()
        request = Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read())
        except HTTPError as error:
            request_id = error.headers.get("x-request-id") if error.headers else None
            logger.warning(
                "provider=openai_interview error_type=%s http_status=%s request_id=%s",
                type(error).__name__,
                error.code,
                request_id or "unknown",
            )
            raise InterviewProviderError(
                "INTERVIEW_PROVIDER_UNAVAILABLE",
                retryable=error.code == 429 or error.code >= 500,
            ) from error
        except (URLError, TimeoutError, ValueError) as error:
            logger.warning(
                "provider=openai_interview error_type=%s http_status=none request_id=unknown",
                type(error).__name__,
            )
            raise InterviewProviderError(
                "INTERVIEW_PROVIDER_UNAVAILABLE", retryable=True
            ) from error
        try:
            for item in payload["output"]:
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        return str(content["text"])
        except (KeyError, TypeError) as error:
            raise InterviewProviderError(
                "INTERVIEW_PROVIDER_SCHEMA_INVALID", retryable=False
            ) from error
        raise InterviewProviderError("INTERVIEW_PROVIDER_SCHEMA_INVALID", retryable=False)
