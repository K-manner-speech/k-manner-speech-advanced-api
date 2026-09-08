from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.ai.interfaces import AIProviderError
from app.schemas.common import JobType
from worker.runtime import ProviderFailure, RetryPlanner
from worker.tts_metrics import TTSMetrics, emit_tts_metrics


@dataclass(frozen=True, slots=True)
class QueueMessage:
    message_id: int
    job_id: UUID


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: UUID
    job_type: JobType
    user_id: UUID
    target_id: UUID
    processing_token: UUID
    attempt_count: int
    schema_repair_count: int
    deadline_at: datetime
    payload: dict[str, Any]
    enqueued_at: datetime | None = None


class QueueRepository(Protocol):
    def recover_expired(self) -> int: ...
    def read_one(self) -> QueueMessage | None: ...
    def claim(self, job_id: UUID) -> ClaimedJob | None: ...
    def complete(self, message: QueueMessage, item: ClaimedJob, output: object) -> bool: ...
    def retry(
        self,
        message: QueueMessage,
        item: ClaimedJob,
        code: str,
        delay_seconds: float,
    ) -> None: ...
    def fail(self, message: QueueMessage, item: ClaimedJob, code: str) -> None: ...
    def discard(self, message: QueueMessage) -> None: ...
    def mark_schema_repair(self, item: ClaimedJob) -> None: ...


class JobExecutor(Protocol):
    def execute(self, item: ClaimedJob, *, repair: bool = False) -> object: ...


class QueueWorker:
    def __init__(
        self,
        repository: QueueRepository,
        executor: JobExecutor,
        maximum_attempts: int,
        *,
        jitter: Callable[[float], float] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._retry_planner = RetryPlanner(maximum_attempts, jitter)
        self._now = now or (lambda: datetime.now().astimezone())

    def run_once(self) -> bool:
        self._repository.recover_expired()
        message = self._repository.read_one()
        if message is None:
            return False
        item = self._repository.claim(message.job_id)
        if item is None:
            self._repository.discard(message)
            return True
        if self._now() >= item.deadline_at:
            self._emit_tts_failure(item, "JOB_DEADLINE_EXCEEDED")
            self._repository.fail(message, item, "JOB_DEADLINE_EXCEEDED")
            return True
        try:
            output = self._execute_with_repair(item)
        except AIProviderError as error:
            self._handle_provider_failure(message, item, error)
            return True
        try:
            completed = self._repository.complete(message, item, output)
        except AIProviderError as error:
            self._handle_provider_failure(message, item, error)
            return True
        if completed and item.job_type is JobType.TTS_GENERATION:
            metrics = getattr(output, "metrics", None)
            if isinstance(metrics, TTSMetrics):
                if item.enqueued_at is not None:
                    metrics.end_to_end_ms = max(
                        0.0,
                        (self._now() - item.enqueued_at).total_seconds() * 1000,
                    )
                emit_tts_metrics(metrics)
        return completed

    def _execute_with_repair(self, item: ClaimedJob) -> object:
        try:
            return self._executor.execute(item)
        except AIProviderError as error:
            if not error.schema_invalid or item.schema_repair_count >= 1:
                raise
            self._repository.mark_schema_repair(item)
            return self._executor.execute(item, repair=True)

    def _handle_provider_failure(
        self,
        message: QueueMessage,
        item: ClaimedJob,
        error: AIProviderError,
    ) -> None:
        self._emit_tts_failure(item, error.code)
        failure = ProviderFailure(
            error.code,
            retryable=error.retryable,
            retry_after_seconds=error.retry_after_seconds,
        )
        decision = self._retry_planner.decide(
            item.attempt_count,
            item.deadline_at,
            self._now(),
            failure,
        )
        if decision.should_retry and decision.delay_seconds is not None:
            self._repository.retry(
                message,
                item,
                error.code,
                decision.delay_seconds,
            )
            return
        self._repository.fail(message, item, error.code)

    def _emit_tts_failure(self, item: ClaimedJob, error_code: str) -> None:
        if item.job_type is not JobType.TTS_GENERATION:
            return
        queue_wait_ms = 0.0
        if item.enqueued_at is not None:
            queue_wait_ms = max(
                0.0, (self._now() - item.enqueued_at).total_seconds() * 1000
            )
        emit_tts_metrics(TTSMetrics.failure(
            job_id=item.job_id,
            message_audio_id=item.target_id,
            text_chars=len(str(item.payload.get("text", ""))),
            queue_wait_ms=queue_wait_ms,
            attempt_count=item.attempt_count,
            error_code=error_code,
        ))
