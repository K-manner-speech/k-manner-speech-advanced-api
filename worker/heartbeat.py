from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


class HeartbeatRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, worker_id: str, queue_name: str, started_at: datetime) -> None:
        if not worker_id.strip() or not queue_name.strip():
            raise ValueError("worker_id and queue_name are required")
        self._session.execute(
            text(
                """
                insert into public.worker_heartbeats
                    (worker_id, queue_name, started_at, last_seen_at)
                values (:worker_id, :queue_name, :started_at, :last_seen_at)
                on conflict (worker_id, queue_name) do update
                set last_seen_at = excluded.last_seen_at
                """
            ),
            {
                "worker_id": worker_id,
                "queue_name": queue_name,
                "started_at": started_at,
                "last_seen_at": datetime.now(UTC),
            },
        )
        self._session.commit()
