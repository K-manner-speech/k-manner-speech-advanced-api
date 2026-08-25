from typing import Annotated, Literal

from pydantic import Field, StrictInt

from app.schemas.base import ContractModel

FeedbackCategory = Literal[
    "honorifics",
    "courtesy",
    "context_fit",
    "naturalness",
]
FeedbackScoreValue = Annotated[StrictInt, Field(ge=0, le=25)]


class FeedbackScore(ContractModel):
    category: FeedbackCategory
    score: FeedbackScoreValue
    max_score: Literal[25]
    strength: str | None
    suggestion: str | None
    original_text: str | None
    recommended_text: str | None


EmotionLabel = Literal[
    "neutral",
    "happy",
    "sad",
    "angry",
    "curious",
    "embarrassment",
]


class FeedbackEmotion(ContractModel):
    label: EmotionLabel
    percentage: Annotated[float, Field(ge=0, le=100)] | None
    sort_order: Annotated[int, Field(ge=1, le=3)]
    source: Literal["text", "voice"]
    evidence: str | None
    impression: str | None


class FeedbackSafeError(ContractModel):
    code: str
    retryable: bool


class FeedbackResponse(ContractModel):
    status: Literal["processing", "ready", "partial", "failed"]
    overall_score: Annotated[int, Field(ge=0, le=100)] | None
    summary: str | None
    scores: list[FeedbackScore]
    emotions: list[FeedbackEmotion]
    error: FeedbackSafeError | None
