from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt

from app.schemas.base import ContractModel
from app.schemas.common import DomainRef

ResultStatus = Literal["processing", "partial", "succeeded", "failed"]
InterviewEvaluationCategory = Literal[
    "question_understanding_fit",
    "answer_structure",
    "specificity_evidence",
    "job_fit_problem_solving",
    "delivery_attitude",
]


class InterviewEvaluationScoreResponse(ContractModel):
    category: InterviewEvaluationCategory
    score: Annotated[StrictInt, Field(ge=1, le=20)]
    max_score: Literal[20]
    strength: str | None
    suggestion: str | None
    evidence: str | None


class InterviewEvaluationResponse(ContractModel):
    status: ResultStatus
    overall_score: Annotated[StrictInt, Field(ge=5, le=100)] | None
    summary: str | None
    scores: list[InterviewEvaluationScoreResponse]
    missing_categories: list[InterviewEvaluationCategory]


class SessionResultSummary(ContractModel):
    id: UUID
    attempt_no: int
    status: ResultStatus
    missing_categories: list[str]
    created_at: datetime


class ResultItem(ContractModel):
    item_type: str
    category: str | None
    title: str
    original_expression: str | None
    recommended_expression: str | None
    explanation: str | None
    evidence: str | None
    source_document_id: UUID | None
    order: int


class SessionResult(SessionResultSummary):
    items: list[ResultItem]
    source_refs: list[DomainRef]
    overall_score: int | None = None
    summary: str | None = None
    interview_evaluation: InterviewEvaluationResponse | None = None
