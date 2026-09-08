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


class ScenarioGoalCondition(ContractModel):
    # OpenAI 구조화 출력은 모든 속성이 required 에 있어야 한다. 기본값을 주면
    # required 에서 빠져 스키마 자체가 400 으로 거부되므로, nullable 로만 둔다.
    condition_key: str = Field(min_length=1, max_length=100)
    achieved: bool
    evidence_sequence_no: StrictInt | None
    reasoning: str | None = Field(max_length=1000)

    @model_validator(mode="after")
    def require_evidence_when_achieved(self) -> ScenarioGoalCondition:
        # 근거 없는 달성은 조기 종료를 잘못 띄운다. 근거를 못 대면 미달성이다.
        if self.achieved and self.evidence_sequence_no is None:
            self.achieved = False
        return self


class ScenarioGoalProgress(ContractModel):
    conditions: list[ScenarioGoalCondition]


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
    score: Literal[5, 10, 15, 20, 25]
    strength: str | None
    suggestion: str | None
    original_text: str | None
    recommended_text: str | None

    @model_validator(mode="after")
    def enforce_behavior_anchor_policy(self) -> GeneralFeedbackScore:
        if self.score < 20:
            self.strength = None
        if self.score <= 10 and not self.suggestion:
            raise ValueError("low general feedback score requires suggestion")
        return self


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


class EvidenceRelevanceDecision(ContractModel):
    # UUID 를 그대로 되돌려 받으면 36자를 한 글자도 틀리지 않고 옮겨 적어야 한다.
    # 실제로 열 번에 한 번꼴로 없는 ID 를 지어내 job 이 통째로 실패했다.
    evidence_no: StrictInt = Field(ge=1)
    support_level: Literal["supported", "partially_supported", "unsupported"]
    supported_claims: list[str] = Field(max_length=5)
    unsupported_claims: list[str] = Field(max_length=5)
    reason: str = Field(min_length=1, max_length=500)


class EvidenceRelevanceResult(ContractModel):
    decisions: list[EvidenceRelevanceDecision]

    @model_validator(mode="after")
    def require_unique_evidence_numbers(self) -> EvidenceRelevanceResult:
        numbers = [item.evidence_no for item in self.decisions]
        if len(numbers) != len(set(numbers)):
            raise ValueError("duplicate evidence relevance evidence_no")
        return self


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

InterviewScoreValue = Literal[4, 8, 12, 16, 20]


class InterviewEvaluationScore(ContractModel):
    category: InterviewEvaluationCategory
    score: InterviewScoreValue = Field(
        description="행동 기준 1~5단계를 4, 8, 12, 16, 20으로 환산한 점수"
    )
    strength: str | None = Field(
        description="16점 이상이고 실제 긍정 행동 근거가 있을 때만 작성하는 강점"
    )
    suggestion: str | None = Field(
        description="4점 또는 8점이면 반드시 작성하는 구체적인 보완 방법"
    )
    evidence: str | None = Field(
        description="판단 근거가 된 실제 사용자 발화의 짧은 인용"
    )


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
        normalized_scores = [
            item if item.score >= 16 else item.model_copy(update={"strength": None})
            for item in normalized_scores
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


class GeneralSessionResultOutput(ContractModel):
    summary: str | None
    items: list[ResultItemOutput]


class InterviewSessionResultOutput(GeneralSessionResultOutput):
    interview_scores: list[InterviewEvaluationScore]
