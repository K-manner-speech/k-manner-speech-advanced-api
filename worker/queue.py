from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.ai.interfaces import AIProviderError
from app.schemas.common import JobType
from worker.runtime import ProviderFailure, RetryPlanner


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
