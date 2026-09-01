from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from app.schemas.base import ContractModel

EmotionLabel = Literal[
    "neutral",
    "happy",
    "sad",
    "angry",
    "curious",
    "embarrassment",
]


class ConversationSummary(ContractModel):
    relation: list[str]
    situation: list[str]
    goals: list[str]
    agreements: list[str]
    unresolved: list[str]
    important_facts: list[str]


class ConversationReply(ContractModel):
    reply: str = Field(min_length=1, max_length=4000)
    persona_emotion: EmotionLabel
    summary: ConversationSummary | None
    interview_answer_complete: bool | None = None
    interview_should_end: bool | None = None


class EmotionAnalysis(ContractModel):
    label: EmotionLabel
    reasoning: str = Field(min_length=1, max_length=1000)
    evidence: str | None = Field(max_length=1000)


GeneralFeedbackCategory = Literal[
    "honorifics",
    "courtesy",
    "context_fit",
    "naturalness",
]


class GeneralFeedbackScore(ContractModel):
    category: GeneralFeedbackCategory
    score: Annotated[StrictInt, Field(ge=0, le=25)]
    strength: str | None
    suggestion: str | None
    original_text: str | None
    recommended_text: str | None


class GeneralFeedbackEmotion(ContractModel):
    label: EmotionLabel
    percentage: Annotated[float, Field(ge=0, le=100)] | None
    evidence: str | None
    impression: str | None


class GeneralFeedback(ContractModel):
    summary: str | None
    scores: list[GeneralFeedbackScore]
    emotions: list[GeneralFeedbackEmotion] = Field(max_length=3)

    @model_validator(mode="after")
    def require_unique_categories(self) -> GeneralFeedback:
        categories = [item.category for item in self.scores]
        if len(categories) != len(set(categories)):
            raise ValueError("duplicate general feedback category")
        return self


class ResultItemOutput(ContractModel):
    item_type: Literal["strength", "improvement"]
    category: str | None
    title: str = Field(min_length=1, max_length=500)
    original_expression: str | None
    recommended_expression: str | None
    explanation: str | None
    evidence: str | None
    source_document_id: UUID | None


InterviewEvaluationCategory = Literal[
    "question_understanding_fit",
    "answer_structure",
    "specificity_evidence",
    "job_fit_problem_solving",
    "delivery_attitude",
]

INTERVIEW_EVALUATION_CATEGORIES: tuple[InterviewEvaluationCategory, ...] = (
    "question_understanding_fit",
    "answer_structure",
    "specificity_evidence",
    "job_fit_problem_solving",
    "delivery_attitude",
)

InterviewScoreValue = Annotated[StrictInt, Field(ge=1, le=20)]


class InterviewEvaluationScore(ContractModel):
    category: InterviewEvaluationCategory
    score: InterviewScoreValue
    strength: str | None
    suggestion: str | None
    evidence: str | None


class InterviewEvaluation(ContractModel):
    status: Literal["succeeded", "partial", "failed"]
    overall_score: Annotated[StrictInt, Field(ge=5, le=100)] | None
    summary: str | None
    scores: list[InterviewEvaluationScore]
    missing_categories: list[InterviewEvaluationCategory]

    @classmethod
    def from_scores(
        cls,
        scores: list[InterviewEvaluationScore],
        summary: str | None,
    ) -> InterviewEvaluation:
        # Structured output이 JSON schema를 통과해도 category 값은 중복될 수 있다.
        # 중복 때문에 평가 전체를 버리지 않고, 같은 항목 중 더 보수적인(낮은)
        # 점수를 남긴다. 빠진 항목은 아래의 partial 계약으로 그대로 드러낸다.
        normalized_by_category: dict[
            InterviewEvaluationCategory, InterviewEvaluationScore
        ] = {}
        for item in scores:
            current = normalized_by_category.get(item.category)
            if current is None or item.score < current.score:
                normalized_by_category[item.category] = item
        normalized_scores = [
            normalized_by_category[category]
            for category in INTERVIEW_EVALUATION_CATEGORIES
            if category in normalized_by_category
        ]
        categories = [item.category for item in normalized_scores]
        missing = [
            category for category in INTERVIEW_EVALUATION_CATEGORIES if category not in categories
        ]
        if not normalized_scores:
            status: Literal["succeeded", "partial", "failed"] = "failed"
        elif missing:
            status = "partial"
        else:
            status = "succeeded"
        return cls(
            status=status,
            overall_score=sum(item.score for item in normalized_scores)
            if status == "succeeded"
            else None,
            summary=summary,
            scores=normalized_scores,
            missing_categories=missing,
        )

    @model_validator(mode="after")
    def validate_derived_fields(self) -> InterviewEvaluation:
        categories = [item.category for item in self.scores]
        if len(categories) != len(set(categories)):
            raise ValueError("duplicate interview evaluation category")
        expected_missing = [
            category for category in INTERVIEW_EVALUATION_CATEGORIES if category not in categories
        ]
        if self.missing_categories != expected_missing:
            raise ValueError("missing_categories does not match scores")
        expected_status = (
            "failed" if not self.scores else "partial" if expected_missing else "succeeded"
        )
        if self.status != expected_status:
            raise ValueError("status does not match interview score completeness")
        expected_total = sum(item.score for item in self.scores) if not expected_missing else None
        if self.overall_score != expected_total:
            raise ValueError("overall_score does not match the five-score sum")
        return self


class SessionResultOutput(ContractModel):
    summary: str | None
    items: list[ResultItemOutput]
    interview_scores: list[InterviewEvaluationScore]
