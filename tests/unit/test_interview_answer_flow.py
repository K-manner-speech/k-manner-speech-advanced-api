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


def test_worker_marks_answer_current_only_after_ai_completion() -> None:
    source = __import__("inspect").getsource(
        __import__("worker.domain_adapters", fromlist=["ConversationAdapter"])
        .ConversationAdapter.complete
    )

    assert "interview_answer_complete" in source
    assert "update public.interview_answers" in source
    assert "interview_should_end" in source
