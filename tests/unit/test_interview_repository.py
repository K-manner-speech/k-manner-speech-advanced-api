from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.repositories.interviews import InterviewRepository


class EmptyMappings:
    def mappings(self) -> EmptyMappings:
        return self

    def __iter__(self) -> Any:
        return iter(())


class CapturingSession:
    def __init__(self) -> None:
        self.sql = ""
        self.parameters: dict[str, object] = {}

    def execute(self, statement: object, parameters: dict[str, object]) -> EmptyMappings:
        self.sql = str(statement)
        self.parameters = parameters
        return EmptyMappings()


class ExistingRow:
    def first(self) -> tuple[int]:
        return (1,)


class DeleteCapturingSession:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.parameters: list[dict[str, object]] = []
        self.committed = False

    def execute(self, statement: object, parameters: dict[str, object]) -> ExistingRow:
        self.sql.append(str(statement))
        self.parameters.append(parameters)
        return ExistingRow()

    def commit(self) -> None:
        self.committed = True


@pytest.mark.parametrize("document_type", ["resume", None])
def test_list_documents_builds_typed_optional_filter_query(
    document_type: str | None,
) -> None:
    session = CapturingSession()
    repository = InterviewRepository(cast(Session, session))
    user_id = uuid4()

    assert repository.list_documents(user_id, 20, document_type) == []

    assert "user_id = :user_id and is_current" in session.sql
    assert ":document_type is null" not in session.sql
    assert session.parameters["user_id"] == user_id
    if document_type is None:
        assert "document_type = :document_type" not in session.sql
        assert "document_type" not in session.parameters
    else:
        assert "document_type = :document_type" in session.sql
        assert session.parameters["document_type"] == document_type


def test_delete_document_scrubs_extracted_content_and_keeps_owner_scope() -> None:
    session = DeleteCapturingSession()
    repository = InterviewRepository(cast(Session, session))
    user_id = uuid4()
    document_id = uuid4()

    assert repository.delete_document(user_id, document_id) is True

    delete_sql = session.sql[0]
    assert "extracted_content = '{}'::jsonb" in delete_sql
    assert "is_current = false" in delete_sql
    assert "deleted_at = now()" in delete_sql
    assert "id = :document_id and user_id = :user_id and is_current" in delete_sql
    assert session.parameters[0] == {"document_id": document_id, "user_id": user_id}
    assert session.committed is False
