from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.services.feedback import SqlFeedbackService


class DecimalFeedbackRepository:
    def get_feedback(self, _user_id: UUID, _message_id: UUID) -> dict[str, Any]:
        return {
            "status": "ready",
            "overall_score": Decimal("96.00"),
            "summary": "좋은 답변입니다.",
            "scores": [
                {
                    "category": "courtesy",
                    "score": Decimal("24.00"),
                    "max_score": Decimal("25.00"),
                    "strength": "정중합니다.",
                    "suggestion": None,
                    "original_text": None,
                    "recommended_text": None,
                }
            ],
            "emotions": [],
            "error_code": None,
        }


def test_feedback_converts_database_numeric_scores_to_contract_integers() -> None:
    service = SqlFeedbackService(DecimalFeedbackRepository())  # type: ignore[arg-type]

    feedback = service.get_feedback(uuid4(), uuid4())

    assert feedback.overall_score == 96
    assert feedback.scores[0].score == 24
    assert feedback.scores[0].max_score == 25
