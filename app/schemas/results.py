from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt

from app.schemas.base import ContractModel
from app.schemas.common import DomainRef

ResultStatus = Literal["processing", "partial", "succeeded", "failed"]
PracticeType = Literal["free_chat", "scenario", "interview"]
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
    room_id: UUID
    attempt_no: int
    practice_type: PracticeType
    display_title: str
    status: ResultStatus
    failure_code: str | None = None
    missing_categories: list[str]
    # 목록에서 점수와 한 줄 요약을 함께 보여 준다. 무엇을 다시 볼지
    # 고르는 화면이라 제목만으로는 고를 수 없다. 아직 생성 중이거나
    # 평가할 발화가 없던 결과에는 둘 다 없다.
    overall_score: int | None = None
    summary: str | None = None
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


class GeneralScore(ContractModel):
    """자유채팅·시나리오 결과의 항목별 점수. 연습 전체를 기준으로 매긴다."""

    category: str
    score: int
    max_score: int
    strength: str | None
    suggestion: str | None
    evidence: str | None


class SessionResult(SessionResultSummary):
    items: list[ResultItem]
    scores: list[GeneralScore] = []
    source_refs: list[DomainRef]
    interview_evaluation: InterviewEvaluationResponse | None = None
