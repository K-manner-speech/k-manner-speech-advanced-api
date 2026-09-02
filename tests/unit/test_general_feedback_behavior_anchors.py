from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.schemas import GeneralFeedbackScore


@pytest.mark.parametrize("score", [5, 10, 15, 20, 25])
def test_general_feedback_accepts_only_behavior_anchor_scores(score: int) -> None:
    parsed = GeneralFeedbackScore(
        category="naturalness",
        score=score,
        strength=None,
        suggestion="더 자연스러운 연결 표현을 사용해 보세요." if score <= 10 else None,
        original_text=None,
        recommended_text=None,
    )

    assert parsed.score == score


@pytest.mark.parametrize("score", [0, 1, 14, 16, 24, 26, 1.5])
def test_general_feedback_rejects_scores_between_behavior_anchors(score: object) -> None:
    with pytest.raises(ValidationError):
        GeneralFeedbackScore(
            category="naturalness",
            score=score,
            strength=None,
            suggestion=None,
            original_text=None,
            recommended_text=None,
        )


def test_general_feedback_does_not_expose_baseline_as_strength() -> None:
    parsed = GeneralFeedbackScore(
        category="courtesy",
        score=15,
        strength="무례하지 않았습니다.",
        suggestion=None,
        original_text="네",
        recommended_text=None,
    )

    assert parsed.strength is None


@pytest.mark.parametrize("score", [5, 10])
def test_low_general_feedback_requires_a_suggestion(score: int) -> None:
    with pytest.raises(ValidationError, match="requires suggestion"):
        GeneralFeedbackScore(
            category="context_fit",
            score=score,
            strength=None,
            suggestion=None,
            original_text="모르겠어요",
            recommended_text=None,
        )
