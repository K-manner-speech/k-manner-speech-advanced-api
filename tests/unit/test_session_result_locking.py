from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from app.schemas.common import JobType
from worker.domain_adapters import SessionResultAdapter


def test_session_result_claim_separates_row_lock_from_feedback_aggregate() -> None:
    session = MagicMock()
    session.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "id": uuid4(),
        "room_id": uuid4(),
        "practice_type": "scenario",
        "title": "고객 불만 응대",
        "interview_configuration_id": None,
        "average_feedback_score": 0,
    }
    session.execute.return_value.mappings.return_value.__iter__.return_value = iter([])
    session.execute.return_value.scalar_one.return_value = 0

    claim = SessionResultAdapter().claim(
        session,
        {
            "job_type": JobType.SESSION_RESULT_GENERATION.value,
            "session_result_id": uuid4(),
            "user_id": uuid4(),
        },
    )

    assert claim is not None
    queries = [str(call.args[0]).lower() for call in session.execute.call_args_list]
    assert "for update of s" in queries[0]
    assert "group by" not in queries[0]
    assert "avg(" in queries[1]
    assert "for update" not in queries[1]


def test_session_result_claim_stops_when_lock_target_is_missing() -> None:
    session = MagicMock()
    session.execute.return_value.mappings.return_value.one_or_none.return_value = None

    claim = SessionResultAdapter().claim(
        session,
        {
            "job_type": JobType.SESSION_RESULT_GENERATION.value,
            "session_result_id": uuid4(),
            "user_id": uuid4(),
        },
    )

    assert claim is None
    assert session.execute.call_count == 1
