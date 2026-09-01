from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.ai.schemas import InterviewEvaluation, InterviewEvaluationScore
from app.schemas.results import InterviewEvaluationResponse, SessionResult


def test_session_result_exposes_fixed_interview_evaluation() -> None:
    categories = (
        "question_understanding_fit",
        "answer_structure",
        "specificity_evidence",
        "job_fit_problem_solving",
        "delivery_attitude",
    )
    room_id = uuid4()
    result = SessionResult(
        id=uuid4(),
        room_id=room_id,
        attempt_no=1,
        practice_type="interview",
        display_title="면접 자기소개",
        status="succeeded",
        missing_categories=[],
        created_at=datetime.now(UTC),
        items=[],
        source_refs=[],
        overall_score=100,
        summary="면접 평가",
        interview_evaluation=InterviewEvaluationResponse(
            status="succeeded",
            overall_score=100,
            summary="면접 평가",
            scores=[
                {
                    "category": category,
                    "score": 20,
                    "max_score": 20,
                    "strength": None,
                    "suggestion": None,
                    "evidence": None,
                }
                for category in categories
            ],
            missing_categories=[],
        ),
    )

    assert result.interview_evaluation is not None
    assert result.interview_evaluation.overall_score == 100


def test_interview_evaluation_recovers_duplicate_category_as_partial() -> None:
    evaluation = InterviewEvaluation.from_scores(
        [
            InterviewEvaluationScore(
                category="answer_structure",
                score=18,
                strength="구조가 명확합니다.",
                suggestion=None,
                evidence="결론부터 설명했습니다.",
            ),
            InterviewEvaluationScore(
                category="answer_structure",
                score=14,
                strength=None,
                suggestion="근거를 보완하세요.",
                evidence="설명이 짧았습니다.",
            ),
        ],
        "일부 항목만 생성됐습니다.",
    )

    assert evaluation.status == "partial"
    assert evaluation.overall_score is None
    assert len(evaluation.scores) == 1
    assert evaluation.scores[0].score == 14
    assert "answer_structure" not in evaluation.missing_categories
