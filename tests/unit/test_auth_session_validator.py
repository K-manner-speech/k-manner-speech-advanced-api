from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import SessionValidationUnavailable, SqlSessionValidator


class ScalarResult:
    def __init__(self, value: bool) -> None:
        self.value = value

    def scalar_one(self) -> bool:
        return self.value


class StubSession:
    def __init__(self, result: bool | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.rolled_back = False

    def execute(self, statement: Any, parameters: dict[str, Any]) -> ScalarResult:
        self.calls.append((str(statement), parameters))
        if isinstance(self.result, Exception):
            raise self.result
        return ScalarResult(self.result)

    def rollback(self) -> None:
        self.rolled_back = True


def test_sql_session_validator_matches_session_owner_and_deletion_state() -> None:
    user_id = uuid4()
    session_id = uuid4()
    session = StubSession(True)

    active = SqlSessionValidator(session).validate(  # type: ignore[arg-type]
        user_id, session_id
    )

    assert active is True
    sql, parameters = session.calls[0]
    assert "from auth.sessions" in sql
    assert "account.delete" in sql
    assert parameters == {
        "session_id": session_id,
        "user_id": user_id,
        "allow_deletion": False,
    }


def test_sql_session_validator_allows_deletion_retry_to_bypass_only_delete_gate() -> None:
    session = StubSession(True)

    SqlSessionValidator(session).validate(  # type: ignore[arg-type]
        uuid4(), uuid4(), allow_account_deletion_in_progress=True
    )

    assert session.calls[0][1]["allow_deletion"] is True


def test_sql_session_validator_rolls_back_and_hides_database_failure() -> None:
    session = StubSession(SQLAlchemyError("database unavailable"))

    with pytest.raises(SessionValidationUnavailable):
        SqlSessionValidator(session).validate(uuid4(), uuid4())  # type: ignore[arg-type]

    assert session.rolled_back is True
