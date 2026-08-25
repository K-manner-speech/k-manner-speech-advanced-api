from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Protocol

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    database: bool
    pgmq_queues: bool
    required_extensions: bool
    timeout_policies: bool
    config: bool
    worker_heartbeat: bool

    @classmethod
    def all_healthy(cls) -> ReadinessReport:
        return cls(
            database=True,
            pgmq_queues=True,
            required_extensions=True,
            timeout_policies=True,
            config=True,
            worker_heartbeat=True,
        )

    @classmethod
    def all_failed(cls) -> ReadinessReport:
        return cls(
            database=False,
            pgmq_queues=False,
            required_extensions=False,
            timeout_policies=False,
            config=False,
            worker_heartbeat=False,
        )

    def failed_checks(self) -> list[str]:
        return [
            report_field.name
            for report_field in fields(self)
            if not getattr(self, report_field.name)
        ]


class ReadinessChecker(Protocol):
    async def check(self) -> ReadinessReport: ...


class UnconfiguredReadinessChecker:
    """Fail closed until concrete infrastructure adapters are installed."""

    async def check(self) -> ReadinessReport:
        return ReadinessReport.all_failed()


class DatabaseReadinessChecker:
    def __init__(
        self,
        engine: Engine,
        queue_names: list[str],
        worker_heartbeat_ttl_seconds: int,
    ) -> None:
        self._engine = engine
        self._queue_names = queue_names
        self._base_queue_names = [name for name in queue_names if not name.endswith("_dlq")]
        self._worker_heartbeat_ttl_seconds = worker_heartbeat_ttl_seconds

    async def check(self) -> ReadinessReport:
        try:
            with self._engine.connect() as connection:
                database = connection.execute(text("select 1")).scalar_one() == 1
                extension_count = connection.execute(
                    text(
                        """
                        select count(*) from pg_extension
                        where extname in ('pgmq', 'vector')
                        """
                    )
                ).scalar_one()
                queue_count = connection.execute(
                    text("select count(*) from pgmq.meta where queue_name = any(:queues)"),
                    {"queues": self._queue_names},
                ).scalar_one()
                policy_count = connection.execute(
                    text(
                        """
                        select count(*) from public.processing_timeout_policies
                        where is_active and job_type = any(:job_types)
                        """
                    ),
                    {
                        "job_types": [
                            "conversation_text",
                            "emotion_analysis",
                            "tts_generation",
                            "turn_feedback",
                            "interview_document_analysis",
                            "interview_configuration_generation",
                            "session_result_generation",
                        ]
                    },
                ).scalar_one()
                heartbeat_count = connection.execute(
                    text(
                        """
                        select count(distinct queue_name)
                        from public.worker_heartbeats
                        where queue_name = any(:queues)
                          and last_seen_at >= now() - make_interval(
                            secs => :ttl_seconds
                          )
                        """
                    ),
                    {
                        "queues": self._base_queue_names,
                        "ttl_seconds": self._worker_heartbeat_ttl_seconds,
                    },
                ).scalar_one()
        except SQLAlchemyError:
            return ReadinessReport.all_failed()

        return ReadinessReport(
            database=database,
            required_extensions=extension_count == 2,
            pgmq_queues=queue_count == len(self._queue_names),
            timeout_policies=policy_count == 7,
            config=True,
            worker_heartbeat=heartbeat_count == len(self._base_queue_names),
        )
