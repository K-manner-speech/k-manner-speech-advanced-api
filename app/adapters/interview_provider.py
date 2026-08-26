from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


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


class OpenAIInterviewProvider:
    _endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 60) -> None:
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
    def parse_questions(payload: str, question_count: int) -> InterviewQuestionResult:
        try:
            parsed = InterviewQuestionResult.model_validate_json(payload)
            return parsed.validate_count(question_count)
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
                "각 질문은 분석 근거와 평가 초점을 포함해야 합니다."
            ),
            input_text=json.dumps(
                {"analysis": analysis, "conditions": conditions},
                ensure_ascii=False,
                default=str,
            ),
            name="interview_question_generation",
            schema=InterviewQuestionResult.model_json_schema(),
        )
        return self.parse_questions(output, question_count)

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
            raise InterviewProviderError(
                "INTERVIEW_PROVIDER_UNAVAILABLE",
                retryable=error.code == 429 or error.code >= 500,
            ) from error
        except (URLError, TimeoutError, ValueError) as error:
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
