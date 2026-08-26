from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.results import InterviewEvaluationResponse, SessionResult


def test_session_result_exposes_fixed_interview_evaluation() -> None:
    categories = (
        "question_understanding_fit",
        "answer_structure",
        "specificity_evidence",
        "job_fit_problem_solving",
        "delivery_attitude",
    )
    result = SessionResult(
        id=uuid4(),
        attempt_no=1,
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
