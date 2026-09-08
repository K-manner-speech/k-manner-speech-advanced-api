from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import BASE_QUEUE_NAMES


@dataclass(frozen=True, slots=True)
class StoredObject:
    bucket_id: str
    storage_path: str


class AccountDeletionRepository:
    # base queue 가 늘어나면 정리 대상도 함께 늘어야 한다. 빠뜨리면 탈퇴한
    # 사용자의 queue message 가 남는다.
    _QUEUES = tuple(name for base in BASE_QUEUE_NAMES for name in (base, f"{base}_dlq"))

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_storage_objects(self, user_id: UUID) -> list[StoredObject]:
        rows = self._session.execute(
            text(
                """
                select bucket_id, name as storage_path
                from storage.objects
                where bucket_id in ('interview-documents', 'message-audio')
                  and name like :user_prefix
                order by bucket_id, name
                """
            ),
            {"user_prefix": f"{user_id}/%"},
        ).mappings()
        return [StoredObject(str(row["bucket_id"]), str(row["storage_path"])) for row in rows]

    def cancel_jobs_and_cleanup_queues(self, user_id: UUID) -> None:
        self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = 'cancelled', progress_stage = null,
                    completed_at = now(), updated_at = now()
                where user_id = :user_id and status in ('queued', 'processing')
                """
            ),
            {"user_id": user_id},
        )
        for queue_name in self._QUEUES:
            self._delete_user_queue_messages(queue_name, user_id)

    def _delete_user_queue_messages(self, queue_name: str, user_id: UUID) -> None:
        self._session.execute(
            text(
                f"""
                with candidates as materialized (
                    select q.msg_id
                    from pgmq.q_{queue_name} q
                    where q.message ->> 'user_id' = :user_id
                       or exists (
                            select 1
                            from public.processing_jobs j
                            where j.user_id = :user_uuid
                              and j.id::text = q.message ->> 'job_id'
                       )
                )
                select pgmq.delete('{queue_name}', msg_id)
                from candidates
                """
            ),
            {"user_id": str(user_id), "user_uuid": user_id},
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
