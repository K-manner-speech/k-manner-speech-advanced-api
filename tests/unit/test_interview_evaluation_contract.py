from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.schemas import (
    INTERVIEW_EVALUATION_CATEGORIES,
    InterviewEvaluation,
    InterviewEvaluationScore,
)


def score(category: str, value: int) -> InterviewEvaluationScore:
    return InterviewEvaluationScore(
        category=category,
        score=value,
        strength="구체적인 근거를 제시했습니다.",
        suggestion="결과를 수치로 연결해 보세요.",
        evidence="답변에 나온 근거",
    )


def test_complete_interview_evaluation_sums_five_integer_scores() -> None:
    evaluation = InterviewEvaluation.from_scores(
        [score(category, 20) for category in INTERVIEW_EVALUATION_CATEGORIES],
        summary="완전한 평가",
    )

    assert evaluation.status == "succeeded"
    assert evaluation.overall_score == 100
    assert evaluation.missing_categories == []


def test_partial_interview_evaluation_has_null_total_and_missing_categories() -> None:
    present = INTERVIEW_EVALUATION_CATEGORIES[:-1]
    evaluation = InterviewEvaluation.from_scores(
        [score(category, 10) for category in present],
        summary="부분 평가",
    )

    assert evaluation.status == "partial"
    assert evaluation.overall_score is None
    assert evaluation.missing_categories == [INTERVIEW_EVALUATION_CATEGORIES[-1]]


def test_empty_interview_evaluation_is_failed() -> None:
    evaluation = InterviewEvaluation.from_scores([], summary=None)

    assert evaluation.status == "failed"
    assert evaluation.overall_score is None
    assert evaluation.missing_categories == list(INTERVIEW_EVALUATION_CATEGORIES)


@pytest.mark.parametrize("invalid_score", [0, 1.5, 21])
def test_interview_score_rejects_out_of_range_or_non_integer(invalid_score: object) -> None:
    with pytest.raises(ValidationError):
        InterviewEvaluationScore(
            category=INTERVIEW_EVALUATION_CATEGORIES[0],
            score=invalid_score,
            strength=None,
            suggestion=None,
            evidence=None,
        )


def test_interview_evaluation_rejects_duplicate_and_unknown_categories() -> None:
    category = INTERVIEW_EVALUATION_CATEGORIES[0]
    with pytest.raises(ValueError, match="duplicate"):
        InterviewEvaluation.from_scores([score(category, 10), score(category, 11)], None)

    with pytest.raises(ValidationError):
        score("unknown", 10)
