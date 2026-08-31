"""종합 결과가 대화방의 조건을 모두 받아 가는지 확인한다."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from worker.domain_adapters import SessionResultAdapter

ROOM = {
    "practice_type": "scenario",
    "title": "학교 식당 위치 묻기",
    "interview_configuration_id": None,
    "goal_snapshot": "선배에게 존댓말로 위치를 묻고 감사를 표현한다",
    "persona_name": "이서준 선배",
    "role_key": "senior",
}

CONDITIONS = [
    {"condition_key": "polite_greeting", "description": "존댓말로 인사한다", "is_required": True},
    {"condition_key": "gratitude", "description": "감사 인사를 한다", "is_required": True},
]

TURN_SCORES = [
    {
        "sequence_no": 1,
        "category": "honorifics",
        "score": 23,
        "max_score": 25,
        "suggestion_text": "더 공손하게",
    },
]


def _claim(room: dict[str, Any] | None = None) -> Any:
    session = MagicMock()
    mappings = session.execute.return_value.mappings.return_value
    mappings.one_or_none.return_value = {
        "id": uuid4(),
        "room_id": uuid4(),
        "scenario_id": uuid4(),
        **(room or ROOM),
    }
    session.execute.return_value.scalar_one.return_value = 77
    # 조건 → 메시지 → 턴 점수 순으로 세 번 조회한다.
    mappings.__iter__.side_effect = [iter([]), iter(CONDITIONS), iter(TURN_SCORES)]
    return SessionResultAdapter().claim(session, {"session_result_id": uuid4(), "user_id": uuid4()})


def test_the_scenario_goal_reaches_the_evaluator() -> None:
    claim = _claim()

    assert claim is not None
    assert claim.payload["goal"] == "선배에게 존댓말로 위치를 묻고 감사를 표현한다"
    assert claim.payload["relationship"] == "senior"
    assert claim.payload["persona_name"] == "이서준 선배"


def test_success_conditions_travel_with_the_transcript() -> None:
    claim = _claim()

    assert claim is not None
    keys = [c["condition_key"] for c in claim.payload["success_conditions"]]
    assert keys == ["polite_greeting", "gratitude"]
    assert all(c["is_required"] for c in claim.payload["success_conditions"])


def test_per_turn_scores_are_kept_beside_their_average() -> None:
    claim = _claim()

    assert claim is not None
    # 평균만으로는 어느 항목이 반복해서 약했는지 알 수 없다.
    assert claim.payload["general_overall_score"] == 77
    assert claim.payload["turn_scores"][0]["category"] == "honorifics"
    assert claim.payload["turn_scores"][0]["sequence_no"] == 1


def test_the_interview_transcript_carries_its_document_evidence() -> None:
    session = MagicMock()
    mappings = session.execute.return_value.mappings.return_value
    mappings.one_or_none.return_value = {
        "id": uuid4(),
        "room_id": uuid4(),
        "scenario_id": None,
        **{**ROOM, "practice_type": "interview", "interview_configuration_id": uuid4()},
    }
    session.execute.return_value.scalar_one.return_value = 0
    mappings.__iter__.side_effect = [iter([]), iter([]), iter([])]

    SessionResultAdapter().claim(session, {"session_result_id": uuid4(), "user_id": uuid4()})

    queries = " ".join(str(call.args[0]) for call in session.execute.call_args_list)
    # 질문을 만들 때 쓴 이력서 원문이 평가에도 실려야 한다.
    assert "q.source_evidence" in queries
