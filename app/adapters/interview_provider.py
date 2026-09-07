"""면접 문서 분석·질문 생성 결과의 계약.

provider 호출은 app/ai/providers 가 하고, 여기에는 그 응답을 검증하는 모델과
worker 가 의존하는 프로토콜만 둔다.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
