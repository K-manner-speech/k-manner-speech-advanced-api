import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.core.errors import ApiError
from app.services.idempotency import IdempotencyRepository, request_fingerprint


class StubExecution:
    def __init__(self, *, first: Any = None, one: Any = None) -> None:
        self._first = first
        self._one = one

    def first(self) -> Any:
        return self._first

    def mappings(self) -> "StubExecution":
        return self

    def one(self) -> Any:
        return self._one

    def one_or_none(self) -> Any:
        return self._one


class RecordingSession:
    def __init__(self, executions: list[StubExecution]) -> None:
        self._executions = executions
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, parameters: dict[str, Any]) -> StubExecution:
        self.calls.append((str(statement), parameters))
        return self._executions.pop(0)


def test_request_fingerprint_is_canonical_and_opaque() -> None:
    first = request_fingerprint({"content": "비밀", "nested": {"a": 1, "b": 2}})
    second = request_fingerprint({"nested": {"b": 2, "a": 1}, "content": "비밀"})
    changed = request_fingerprint({"content": "다름", "nested": {"a": 1, "b": 2}})

    assert first == second
    assert first != changed
    assert isinstance(first, bytes)
    assert len(first) == 32
    assert "비밀" not in first.hex()


def test_new_claim_keeps_expiry_null_until_completion() -> None:
    session = RecordingSession([StubExecution(first=(uuid4(),))])

    claim = IdempotencyRepository(session).claim(  # type: ignore[arg-type]
        uuid4(), "interview_setup.create", uuid4(), b"x" * 32, 30
    )

    sql, parameters = session.calls[0]
    assert claim.kind == "claimed"
    assert re.search(r"(?<!lease_)expires_at", sql) is None
    assert "expires_at" not in parameters


def test_complete_clears_claim_and_sets_retention_expiry() -> None:
    session = RecordingSession([StubExecution(first=(uuid4(),))])

    IdempotencyRepository(session).complete(  # type: ignore[arg-type]
        uuid4(),
        "interview_setup.create",
        uuid4(),
        uuid4(),
        201,
        {"id": str(uuid4())},
        "InterviewSetup.v1",
        86_400,
    )

    sql, parameters = session.calls[0]
    assert "claim_token = null" in sql
    assert parameters["expires_at"] - parameters["completed_at"] == timedelta(days=1)


def test_active_claim_uses_documented_retryable_conflict_code() -> None:
    fingerprint = b"x" * 32
    session = RecordingSession(
        [
            StubExecution(first=None),
            StubExecution(
                one={
                    "request_fingerprint": fingerprint,
                    "state": "in_progress",
                    "claim_token": uuid4(),
                    "lease_expires_at": datetime.now(UTC) + timedelta(seconds=30),
                    "response_status": None,
                    "response_body": None,
                    "error_retryable": None,
                }
            ),
        ]
    )

    with pytest.raises(ApiError) as captured:
        IdempotencyRepository(session).claim(  # type: ignore[arg-type]
            uuid4(), "interview_setup.create", uuid4(), fingerprint, 30
        )

    assert captured.value.status_code == 409
    assert captured.value.code == "IDEMPOTENCY_REQUEST_IN_PROGRESS"
    assert captured.value.retryable is True


def test_retryable_failure_releases_claim_for_reconciliation() -> None:
    session = RecordingSession([StubExecution(first=(uuid4(),))])

    IdempotencyRepository(session).fail_retryable(  # type: ignore[arg-type]
        uuid4(),
        "account.delete",
        uuid4(),
        uuid4(),
        "ACCOUNT_DELETION_INCOMPLETE",
        86_400,
    )

    sql, parameters = session.calls[0]
    assert "state = 'failed'" in sql
    assert "claim_token = null" in sql
    assert parameters["expires_at"] - parameters["completed_at"] == timedelta(days=1)
