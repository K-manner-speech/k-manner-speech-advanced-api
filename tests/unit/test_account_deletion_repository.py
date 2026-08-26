from typing import Any
from uuid import uuid4

from app.repositories.account import AccountDeletionRepository, StoredObject


class RowsResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> "RowsResult":
        return self

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._rows)


class RecordingSession:
    def __init__(self, results: list[RowsResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, parameters: dict[str, Any]) -> RowsResult:
        self.calls.append((str(statement), parameters))
        return self.results.pop(0)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def test_storage_inventory_uses_user_prefix_across_private_buckets() -> None:
    user_id = uuid4()
    session = RecordingSession(
        [
            RowsResult(
                [
                    {
                        "bucket_id": "interview-documents",
                        "storage_path": f"{user_id}/orphan.pdf",
                    },
                    {
                        "bucket_id": "message-audio",
                        "storage_path": f"{user_id}/room/audio.wav",
                    },
                ]
            )
        ]
    )

    objects = AccountDeletionRepository(session).list_storage_objects(user_id)  # type: ignore[arg-type]

    assert objects == [
        StoredObject("interview-documents", f"{user_id}/orphan.pdf"),
        StoredObject("message-audio", f"{user_id}/room/audio.wav"),
    ]
    sql, parameters = session.calls[0]
    assert "from storage.objects" in sql.lower()
    assert "delete from storage.objects" not in sql.lower()
    assert parameters["user_prefix"] == f"{user_id}/%"


def test_account_cleanup_cancels_jobs_and_removes_all_user_queue_messages() -> None:
    session = RecordingSession([RowsResult() for _ in range(7)])

    AccountDeletionRepository(session).cancel_jobs_and_cleanup_queues(uuid4())  # type: ignore[arg-type]

    combined_sql = "\n".join(sql for sql, _ in session.calls)
    assert "set status = 'cancelled'" in combined_sql
    for queue_name in (
        "conversation_text",
        "interactive_ai",
        "document_analysis",
        "conversation_text_dlq",
        "interactive_ai_dlq",
        "document_analysis_dlq",
    ):
        assert queue_name in combined_sql
