from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.core.errors import ApiError
from app.repositories.conversation import (
    InterviewQuestionModeError,
    InterviewQuestionOrderError,
)
from app.schemas.rooms import MessageCreateRequest
from app.services.conversation import SqlConversationService


class RejectingRepository:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.committed = False

    def create_message_and_job(self, *_args: Any, **_kwargs: Any) -> Any:
        raise self.error

    def commit(self) -> None:
        self.committed = True


class CompletingRepository:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.committed = False

    def complete_interview(self, user_id: Any, room_id: Any, deadline_seconds: int) -> Any:
        del user_id, room_id
        assert deadline_seconds > 0
        return self.row

    def commit(self) -> None:
        self.committed = True


def request(question_id: bool = True) -> MessageCreateRequest:
    request_id = uuid4()
    return MessageCreateRequest(
        content="답변입니다.",
        input_mode="text",
        current_interview_question_id=uuid4() if question_id else None,
        client_request_id=request_id,
    )


@pytest.mark.parametrize(
    ("repository_error", "status_code", "code"),
    [
        (InterviewQuestionModeError(), 422, "INTERVIEW_QUESTION_MODE_INVALID"),
        (InterviewQuestionOrderError(), 409, "INTERVIEW_QUESTION_OUT_OF_ORDER"),
    ],
)
def test_interview_question_failures_are_safe_and_atomic(
    repository_error: Exception, status_code: int, code: str
) -> None:
    repository = RejectingRepository(repository_error)
    service = SqlConversationService(repository, 20, 4)  # type: ignore[arg-type]
    body = request()

    with pytest.raises(ApiError) as raised:
        service.create_message(uuid4(), uuid4(), body, body.client_request_id)

    assert raised.value.status_code == status_code
    assert raised.value.code == code, "AC-T5-INTERVIEW-ORDER"
    assert repository.committed is False


def test_repository_contains_atomic_interview_answer_contract() -> None:
    source = __import__("inspect").getsource(
        __import__(
            "app.repositories.conversation", fromlist=["ConversationRepository"]
        ).ConversationRepository.create_message_and_job
    )

    assert "order by q.sequence_no, q.id" in source, "AC-T5-INTERVIEW-ORDER"
    assert "insert into public.interview_answers" in source, "AC-T5-INTERVIEW-ORDER"
    assert "current_interview_question_id" in source, "AC-T5-INTERVIEW-ORDER"
    assert "a.is_current" in source, "incomplete answers must keep the current question"
    assert "where question_id = :question_id and room_id = :room_id" in source


def test_worker_marks_answer_current_only_after_ai_completion() -> None:
    source = __import__("inspect").getsource(
        __import__("worker.domain_adapters", fromlist=["ConversationAdapter"])
        .ConversationAdapter.complete
    )

    assert "interview_answer_complete" in source
    assert "update public.interview_answers" in source
    assert "interview_should_end" in source


def test_worker_payload_enforces_total_interview_answer_limit() -> None:
    source = __import__("inspect").getsource(
        __import__("worker.domain_adapters", fromlist=["ConversationAdapter"])
        .ConversationAdapter.claim
    )

    assert "interview_question_count" in source
    assert "interview_answer_count" in source
    assert "answer_count >= question_count * 3" in source
    assert "interview_answer_limit_reached" in source


def test_worker_passes_evaluation_focus_without_resume_evidence() -> None:
    source = __import__("inspect").getsource(
        __import__("worker.domain_adapters", fromlist=["ConversationAdapter"])
        .ConversationAdapter.claim
    )

    assert "question.evaluation_focus as interview_question_evaluation_focus" in source
    assert '"evaluation_focus": row["interview_question_evaluation_focus"]' in source
    assert '"source_evidence"' not in source


def test_worker_waits_for_manual_completion_after_final_reply() -> None:
    source = __import__("inspect").getsource(
        __import__("worker.domain_adapters", fromlist=["ConversationAdapter"])
        .ConversationAdapter.complete
    )

    assert "awaiting_user_end" in source
    assert "if should_complete:" not in source


def test_manual_interview_completion_returns_completed_room() -> None:
    room_id = uuid4()
    row = {
        "id": room_id,
        "title": "모의 면접",
        "practice_type": "interview",
        "persona_id": None,
        "scenario_id": None,
        "status": "completed",
        "turn_count": 3,
        "ended_reason": "completed",
        "started_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:10:00Z",
        "updated_at": "2026-01-01T00:10:00Z",
    }
    repository = CompletingRepository(row)
    service = SqlConversationService(repository, 20, 4)  # type: ignore[arg-type]

    completed = service.complete_interview(uuid4(), room_id)

    assert completed.status == "completed"
    assert repository.committed is True


def test_manual_interview_completion_rejects_invalid_room_state() -> None:
    repository = CompletingRepository(None)
    service = SqlConversationService(repository, 20, 4)  # type: ignore[arg-type]

    with pytest.raises(ApiError) as raised:
        service.complete_interview(uuid4(), uuid4())

    assert raised.value.status_code == 409
    assert raised.value.code == "INTERVIEW_NOT_READY_TO_END"
    assert repository.committed is False
