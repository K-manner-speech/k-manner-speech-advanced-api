"""턴 피드백이 채점 대상 문장과 판단 배경을 나눠 전달하는지 확인한다."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from worker.domain_adapters import FeedbackAdapter


def _claim(
    preceding: list[dict[str, Any]],
    summary: str | None = None,
    through_message_id: Any = None,
) -> tuple[Any, MagicMock]:
    session = MagicMock()
    session.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "id": uuid4(),
        "processing_token": uuid4(),
        "content": "다음에 또 봐요!",
        "room_id": uuid4(),
        "sequence_no": 7,
        "practice_type": "scenario",
        "title": "학교 식당 위치 묻기",
        "goal_snapshot": "선배에게 존댓말로 위치를 묻고 감사를 표현한다",
        "persona_name": "이서준 선배",
        "role_key": "senior",
        "summary_text": summary,
        "summarized_through_message_id": through_message_id,
    }
    session.execute.return_value.mappings.return_value.__iter__.return_value = iter(preceding)
    claim = FeedbackAdapter().claim(session, {"turn_feedback_id": uuid4(), "user_id": uuid4()})
    return claim, session


def test_the_scored_sentence_is_separated_from_its_background() -> None:
    claim, _ = _claim([])

    assert claim is not None
    assert claim.payload["target_utterance"] == "다음에 또 봐요!"
    # 배경은 context 아래로 내려가 채점 대상과 섞이지 않는다.
    assert "goal" not in claim.payload
    assert claim.payload["context"]["goal"].startswith("선배에게")


def test_the_relationship_travels_with_the_utterance() -> None:
    claim, _ = _claim([])

    assert claim is not None
    assert claim.payload["context"]["relationship"] == "senior"
    assert claim.payload["context"]["persona_name"] == "이서준 선배"


def test_the_persona_line_being_answered_is_singled_out() -> None:
    claim, _ = _claim(
        [
            {"sequence_no": 3, "sender_type": "user", "content": "감사합니다."},
            {"sequence_no": 4, "sender_type": "persona", "content": "별말씀을요!"},
            {"sequence_no": 5, "sender_type": "user", "content": "완료 처리는요?"},
            {"sequence_no": 6, "sender_type": "persona", "content": "그냥 마무리하면 돼."},
        ]
    )

    assert claim is not None
    context = claim.payload["context"]
    # 가장 가까운 페르소나 발화라야 응답 적절성을 판단할 수 있다.
    assert context["previous_persona_message"] == "그냥 마무리하면 돼."
    assert [m["sequence_no"] for m in context["preceding_messages"]] == [3, 4, 5, 6]


def test_a_room_without_a_summary_keeps_every_earlier_message() -> None:
    opening = [
        {"sequence_no": 1, "sender_type": "user", "content": "학생 식당이 어딘지 아세요?"},
        {"sequence_no": 2, "sender_type": "persona", "content": "학생회관 1층이에요."},
        {"sequence_no": 3, "sender_type": "user", "content": "감사합니다."},
    ]
    claim, session = _claim(opening, summary=None, through_message_id=None)

    assert claim is not None
    context = claim.payload["context"]
    # 요약이 없는 방에서는 첫 발화까지 남아야 목표 달성 여부를 알 수 있다.
    assert [m["sequence_no"] for m in context["preceding_messages"]] == [1, 2, 3]
    assert context["earlier_summary"] is None
    through = [
        call.args[1]["through_message_id"]
        for call in session.execute.call_args_list
        if len(call.args) > 1
        and isinstance(call.args[1], dict)
        and "through_message_id" in call.args[1]
    ]
    assert through == [None]


def test_a_summarised_room_only_resends_what_the_summary_missed() -> None:
    marker = uuid4()
    _, session = _claim([], summary='{"situation":[]}', through_message_id=marker)

    through = [
        call.args[1]["through_message_id"]
        for call in session.execute.call_args_list
        if len(call.args) > 1
        and isinstance(call.args[1], dict)
        and "through_message_id" in call.args[1]
    ]
    assert through == [marker]


def test_an_opening_turn_has_no_previous_persona_line() -> None:
    claim, _ = _claim([])

    assert claim is not None
    assert claim.payload["context"]["previous_persona_message"] is None
    assert claim.payload["context"]["preceding_messages"] == []


def test_the_earlier_summary_rides_along_when_one_exists() -> None:
    claim, _ = _claim([], summary='{"situation":["위치를 안내받음"]}')

    assert claim is not None
    assert "위치를 안내받음" in claim.payload["context"]["earlier_summary"]
