from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.ai.rag import EvidenceChunk
from app.schemas.common import JobType
from app.services.jobs import get_job_target_column
from worker.queue import ClaimedJob, QueueMessage
from worker.runtime import JOB_QUEUE_NAMES

# 단일 출처는 app.services.jobs 다.
TARGET_COLUMNS: dict[JobType, str] = {
    job_type: get_job_target_column(job_type) for job_type in JobType
}

TARGET_STATE: dict[JobType, tuple[str, str, bool]] = {
    JobType.CONVERSATION_TEXT: ("message_ai_processing", "processing_status", True),
    JobType.EMOTION_ANALYSIS: ("message_emotion_analysis", "processing_status", True),
    JobType.TTS_GENERATION: ("message_audio", "generation_status", True),
    JobType.TURN_FEEDBACK: ("turn_feedback", "analysis_status", True),
    JobType.INTERVIEW_DOCUMENT_ANALYSIS: (
        "interview_document_analyses",
        "processing_status",
        True,
    ),
    JobType.INTERVIEW_CONFIGURATION_GENERATION: (
        "interview_configurations",
        "status",
        True,
    ),
    JobType.SESSION_RESULT_GENERATION: ("session_results", "result_status", False),
    JobType.SCENARIO_GOAL_PROGRESS: ("room_goal_evaluations", "evaluation_status", True),
}


def _expired_feedback_retry_delay(
    job_type: JobType,
    attempt_count: int,
    maximum_attempts: int,
) -> float | None:
    if job_type is not JobType.TURN_FEEDBACK or attempt_count >= maximum_attempts:
        return None
    return float(2 ** max(0, attempt_count - 1))


@dataclass(frozen=True, slots=True)
class TargetClaim:
    target_id: UUID
    processing_token: UUID
    stage: str
    payload: dict[str, Any]


class SqlDomainAdapter(Protocol):
    def claim(self, session: Session, job: Mapping[str, Any]) -> TargetClaim | None: ...
    def complete(self, session: Session, item: ClaimedJob, output: object) -> bool: ...
    def retry(
        self,
        session: Session,
        item: ClaimedJob,
        code: str,
        next_attempt_at: datetime,
    ) -> None: ...
    def fail(self, session: Session, item: ClaimedJob, code: str) -> None: ...


class SqlQueueRepository:
    def __init__(
        self,
        session: Session,
        queue_name: str,
        visibility_timeout_seconds: int,
        adapters: Mapping[JobType, SqlDomainAdapter],
    ) -> None:
        if visibility_timeout_seconds <= 0:
            raise ValueError("visibility timeout must be positive")
        self._session = session
        self._queue_name = queue_name
        self._dlq_name = f"{queue_name}_dlq"
        self._visibility_timeout_seconds = visibility_timeout_seconds
        self._adapters = dict(adapters)

    def recover_expired(self) -> int:
        jobs = list(
            self._session.execute(
                text(
                    """
                    select j.id, j.user_id, j.job_type, j.transport_attempt_count,
                           message_ai_processing_id, message_emotion_analysis_id,
                           message_audio_id, turn_feedback_id,
                           interview_document_analysis_id, interview_configuration_id,
                           session_result_id, room_goal_evaluation_id,
                           p.timeout_seconds, p.max_attempts
                    from public.processing_jobs j
                    join public.processing_timeout_policies p on p.job_type = j.job_type
                    where j.status = 'processing' and j.deadline_at <= now()
                      and p.is_active
                    for update of j skip locked
                    """
                )
            ).mappings()
        )
        recovered = 0
        try:
            for job in jobs:
                job_type = JobType(str(job["job_type"]))
                if JOB_QUEUE_NAMES[job_type] != self._queue_name:
                    continue
                target_id = self._target_id(dict(job), job_type)
                token = self._processing_token(job_type, target_id)
                item = ClaimedJob(
                    job_id=UUID(str(job["id"])),
                    job_type=job_type,
                    user_id=UUID(str(job["user_id"])),
                    target_id=target_id,
                    processing_token=token,
                    attempt_count=int(job["transport_attempt_count"]),
                    schema_repair_count=0,
                    deadline_at=datetime.now(UTC),
                    payload={},
                )
                retry_delay = _expired_feedback_retry_delay(
                    job_type,
                    item.attempt_count,
                    int(job["max_attempts"]),
                )
                if retry_delay is not None:
                    retried = self._retry_expired_feedback(
                        item,
                        retry_delay,
                        int(job["timeout_seconds"]),
                    )
                    if retried:
                        recovered += 1
                        continue
                self._adapters[job_type].fail(
                    self._session, item, "JOB_DEADLINE_EXCEEDED"
                )
                updated = self._session.execute(
                    text(
                        """
                        update public.processing_jobs
                        set status = 'failed', progress_stage = null,
                            error_code = 'JOB_DEADLINE_EXCEEDED',
                            error_retryable = false, error_meta = null,
                            completed_at = now(), updated_at = now()
                        where id = :job_id and status = 'processing'
                        returning id
                        """
                    ),
                    {"job_id": item.job_id},
                ).first()
                if updated is None:
                    continue
                self._session.execute(
                    text("select pgmq.send(:queue, cast(:payload as jsonb))"),
                    {
                        "queue": self._dlq_name,
                        "payload": json.dumps(
                            {
                                "job_id": str(item.job_id),
                                "job_type": item.job_type.value,
                                "attempts": item.attempt_count,
                                "error_code": "JOB_DEADLINE_EXCEEDED",
                                "failed_at": datetime.now(UTC).isoformat(),
                            }
                        ),
                    },
                )
                recovered += 1
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return recovered

    def _retry_expired_feedback(
        self,
        item: ClaimedJob,
        delay_seconds: float,
        timeout_seconds: int,
    ) -> bool:
        next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        deadline_at = next_attempt_at + timedelta(seconds=timeout_seconds)
        new_token = self._session.execute(
            text(
                """
                update public.turn_feedback
                set processing_token = gen_random_uuid(),
                    error_code = 'JOB_DEADLINE_EXCEEDED',
                    next_attempt_at = :next_attempt_at,
                    deadline_at = :deadline_at, updated_at = now()
                where id = :target_id and processing_token = :token
                  and analysis_status = 'processing'
                returning processing_token
                """
            ),
            {
                "target_id": item.target_id,
                "token": item.processing_token,
                "next_attempt_at": next_attempt_at,
                "deadline_at": deadline_at,
            },
        ).scalar_one_or_none()
        if new_token is None:
            return False
        updated = self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = 'queued', progress_stage = null,
                    error_code = null, error_retryable = null, error_meta = null,
                    next_attempt_at = :next_attempt_at, deadline_at = :deadline_at,
                    updated_at = now()
                where id = :job_id and status = 'processing'
                returning id
                """
            ),
            {
                "job_id": item.job_id,
                "next_attempt_at": next_attempt_at,
                "deadline_at": deadline_at,
            },
        ).first()
        if updated is None:
            raise RuntimeError("expired feedback job state changed while locked")
        self._session.execute(
            text("select pgmq.send(:queue, cast(:payload as jsonb), :delay_at)"),
            {
                "queue": self._queue_name,
                "payload": json.dumps(
                    {"job_id": str(item.job_id), "user_id": str(item.user_id)}
                ),
                "delay_at": next_attempt_at,
            },
        )
        return True

    def _target_id(self, job: Mapping[str, Any], job_type: JobType) -> UUID:
        target_id = job[TARGET_COLUMNS[job_type]]
        if target_id is None:
            raise RuntimeError("expired job has no target")
        return UUID(str(target_id))

    def _processing_token(self, job_type: JobType, target_id: UUID) -> UUID:
        table_name, status_column, has_token = TARGET_STATE[job_type]
        if not has_token:
            return UUID(int=0)
        token = self._session.execute(
            text(
                f"""
                select processing_token
                from public.{table_name}
                where id = :target_id and {status_column} = 'processing'
                for update
                """
            ),
            {"target_id": target_id},
        ).scalar_one_or_none()
        return UUID(str(token)) if token is not None else UUID(int=0)

    def read_one(self) -> QueueMessage | None:
        row = (
            self._session.execute(
                text(
                    "select msg_id, message from "
                    "pgmq.read(:queue, :visibility_timeout, 1, '{}'::jsonb)"
                ),
                {
                    "queue": self._queue_name,
                    "visibility_timeout": self._visibility_timeout_seconds,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        try:
            return QueueMessage(
                message_id=int(row["msg_id"]),
                job_id=UUID(str(row["message"]["job_id"])),
            )
        except (KeyError, TypeError, ValueError):
            self.discard(QueueMessage(int(row["msg_id"]), UUID(int=0)))
            return None

    def claim(self, job_id: UUID) -> ClaimedJob | None:
        job = (
            self._session.execute(
                text(
                    """
                    select id, user_id, job_type, status, transport_attempt_count,
                           schema_repair_count, deadline_at, next_attempt_at, created_at,
                           message_ai_processing_id, message_emotion_analysis_id,
                           message_audio_id, turn_feedback_id,
                           interview_document_analysis_id, interview_configuration_id,
                           session_result_id, room_goal_evaluation_id
                    from public.processing_jobs
                    where id = :job_id and status = 'queued'
                      and (next_attempt_at is null or next_attempt_at <= now())
                    for update
                    """
                ),
                {"job_id": job_id},
            )
            .mappings()
            .one_or_none()
        )
        if job is None:
            self._session.rollback()
            return None
        try:
            job_type = JobType(str(job["job_type"]))
        except ValueError:
            self._session.rollback()
            return None
        if JOB_QUEUE_NAMES[job_type] != self._queue_name or job_type not in self._adapters:
            self._session.rollback()
            return None
        claim = self._adapters[job_type].claim(self._session, dict(job))
        if claim is None:
            self._session.rollback()
            return None
        updated = self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = 'processing', progress_stage = :stage,
                    transport_attempt_count = transport_attempt_count + 1,
                    started_at = coalesce(started_at, now()),
                    next_attempt_at = null, updated_at = now()
                where id = :job_id and status = 'queued'
                returning transport_attempt_count
                """
            ),
            {"job_id": job_id, "stage": claim.stage},
        ).scalar_one_or_none()
        if updated is None:
            self._session.rollback()
            return None
        self._session.commit()
        deadline_at = job["deadline_at"]
        if deadline_at is None:
            raise RuntimeError("claimed job has no deadline")
        return ClaimedJob(
            job_id=job_id,
            job_type=job_type,
            user_id=job["user_id"],
            target_id=claim.target_id,
            processing_token=claim.processing_token,
            attempt_count=int(updated),
            schema_repair_count=int(job["schema_repair_count"]),
            deadline_at=deadline_at,
            payload=claim.payload,
            enqueued_at=job["created_at"],
        )

    def complete(self, message: QueueMessage, item: ClaimedJob, output: object) -> bool:
        if not self._adapters[item.job_type].complete(self._session, item, output):
            self._session.rollback()
            return False
        succeeded = self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = 'succeeded', progress_stage = null,
                    error_code = null, error_retryable = null, error_meta = null,
                    completed_at = now(), updated_at = now()
                where id = :job_id and status = 'processing'
                returning id
                """
            ),
            {"job_id": item.job_id},
        ).first()
        if succeeded is None:
            self._session.rollback()
            return False
        self._delete_source(message.message_id)
        self._session.commit()
        return True

    def retry(
        self,
        message: QueueMessage,
        item: ClaimedJob,
        code: str,
        delay_seconds: float,
    ) -> None:
        next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        self._adapters[item.job_type].retry(
            self._session, item, code, next_attempt_at
        )
        updated = self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = 'queued', progress_stage = null, error_code = null,
                    error_retryable = null, error_meta = null,
                    next_attempt_at = :next_attempt_at, updated_at = now()
                where id = :job_id and status = 'processing'
                returning id
                """
            ),
            {"job_id": item.job_id, "next_attempt_at": next_attempt_at},
        ).first()
        if updated is None:
            self._session.rollback()
            return
        self._session.execute(
            text("select pgmq.send(:queue, cast(:payload as jsonb), :delay_at)"),
            {
                "queue": self._queue_name,
                "payload": json.dumps(
                    {"job_id": str(item.job_id), "user_id": str(item.user_id)}
                ),
                "delay_at": next_attempt_at,
            },
        )
        self._delete_source(message.message_id)
        self._session.commit()

    def fail(self, message: QueueMessage, item: ClaimedJob, code: str) -> None:
        self._adapters[item.job_type].fail(self._session, item, code)
        updated = self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = 'failed', progress_stage = null, error_code = :code,
                    error_retryable = false, error_meta = null,
                    completed_at = now(), updated_at = now()
                where id = :job_id and status = 'processing'
                returning id
                """
            ),
            {"job_id": item.job_id, "code": code},
        ).first()
        if updated is None:
            self._session.rollback()
            return
        self._session.execute(
            text("select pgmq.send(:queue, cast(:payload as jsonb))"),
            {
                "queue": self._dlq_name,
                "payload": json.dumps(
                    {
                        "job_id": str(item.job_id),
                        "job_type": item.job_type.value,
                        "attempts": item.attempt_count,
                        "error_code": code,
                        "failed_at": datetime.now(UTC).isoformat(),
                    }
                ),
            },
        )
        self._delete_source(message.message_id)
        self._session.commit()

    def discard(self, message: QueueMessage) -> None:
        self._delete_source(message.message_id)
        self._session.commit()

    def mark_schema_repair(self, item: ClaimedJob) -> None:
        updated = self._session.execute(
            text(
                """
                update public.processing_jobs
                set schema_repair_count = schema_repair_count + 1, updated_at = now()
                where id = :job_id and status = 'processing'
                  and schema_repair_count = 0
                returning id
                """
            ),
            {"job_id": item.job_id},
        ).first()
        if updated is None:
            self._session.rollback()
            raise RuntimeError("schema repair claim was lost")
        self._session.commit()

    def extend_visibility(self, message_id: int) -> None:
        self._session.execute(
            text("select pgmq.set_vt(:queue, :message_id, :visibility_timeout)"),
            {
                "queue": self._queue_name,
                "message_id": message_id,
                "visibility_timeout": self._visibility_timeout_seconds,
            },
        )
        self._session.commit()

    def _delete_source(self, message_id: int) -> None:
        self._session.execute(
            text("select pgmq.delete(:queue, :message_id)"),
            {"queue": self._queue_name, "message_id": message_id},
        )


class SqlEvidenceRetriever:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def retrieve(
        self,
        *,
        user_id: UUID,
        document_versions: dict[UUID, int],
        query_embedding: list[float],
        threshold: float,
        top_k: int,
        sections: tuple[str, ...] | None = None,
    ) -> list[EvidenceChunk]:
        if not document_versions:
            return []
        vector = "[" + ",".join(str(value) for value in query_embedding) + "]"
        versions = {str(key): value for key, value in document_versions.items()}
        section_filter = "and section = any(:sections)" if sections else ""
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    """
                    select id, user_id, document_id, document_version, content,
                           section,
                           1 - (embedding::halfvec(3072) <=>
                                cast(:embedding as halfvec(3072))) as similarity
                    from public.document_chunks
                    where user_id = :user_id
                      and document_id = any(:document_ids)
                      and document_version = (
                        cast(:versions as jsonb) ->> document_id::text
                      )::integer
                      """
                    + section_filter
                    + """
                      and 1 - (embedding::halfvec(3072) <=>
                               cast(:embedding as halfvec(3072))) >= :threshold
                    order by embedding::halfvec(3072) <=>
                             cast(:embedding as halfvec(3072)), id
                    limit :top_k
                    """
                ),
                {
                    "user_id": user_id,
                    "document_ids": list(document_versions),
                    "versions": json.dumps(versions),
                    "embedding": vector,
                    "threshold": threshold,
                    "top_k": top_k,
                    **({"sections": list(sections)} if sections else {}),
                },
            ).mappings()
            return [
                EvidenceChunk(
                    id=row["id"],
                    user_id=row["user_id"],
                    document_id=row["document_id"],
                    document_version=row["document_version"],
                    text=row["content"],
                    section=row["section"],
                    similarity=float(row["similarity"]),
                )
                for row in rows
            ]
