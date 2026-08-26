from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.errors import ApiError
from app.services.interviews import SqlInterviewService


class DeleteRepository:
    def __init__(self, delete_result: bool = True) -> None:
        self.delete_result = delete_result
        self.committed = False
        self.rolled_back = False

    def get_document(
        self, _user_id: UUID, document_id: UUID, include_storage: bool = False
    ) -> dict[str, Any]:
        assert include_storage is True
        return {"id": document_id, "current": True, "storage_path": "owner/file.pdf"}

    def delete_document(self, _user_id: UUID, _document_id: UUID) -> bool:
        return self.delete_result

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class DeleteStorage:
    def __init__(self, fails: bool = False) -> None:
        self.fails = fails
        self.deleted = False

    def delete(self, _bucket: str, _path: str) -> None:
        if self.fails:
            raise RuntimeError("storage unavailable")
        self.deleted = True


def service(repository: DeleteRepository, storage: DeleteStorage) -> SqlInterviewService:
    return SqlInterviewService(repository, storage, 20, 100)  # type: ignore[arg-type]


def test_document_state_change_prevents_storage_delete() -> None:
    repository = DeleteRepository(delete_result=False)
    storage = DeleteStorage()

    with pytest.raises(ApiError) as raised:
        service(repository, storage).delete_document(uuid4(), uuid4(), uuid4())

    assert raised.value.code == "DOCUMENT_STATE_CHANGED", "AC-T6-DELETE-CONSISTENCY"
    assert repository.rolled_back is True, "AC-T6-DELETE-CONSISTENCY"
    assert repository.committed is False
    assert storage.deleted is False


def test_storage_failure_rolls_back_database_delete() -> None:
    repository = DeleteRepository()
    storage = DeleteStorage(fails=True)

    with pytest.raises(ApiError) as raised:
        service(repository, storage).delete_document(uuid4(), uuid4(), uuid4())

    assert raised.value.code == "STORAGE_UNAVAILABLE"
    assert repository.rolled_back is True, "AC-T6-DELETE-CONSISTENCY"
    assert repository.committed is False


def test_successful_storage_delete_commits_database_delete() -> None:
    repository = DeleteRepository()
    storage = DeleteStorage()

    service(repository, storage).delete_document(uuid4(), uuid4(), uuid4())

    assert storage.deleted is True
    assert repository.committed is True, "AC-T6-DELETE-CONSISTENCY"
    assert repository.rolled_back is False
