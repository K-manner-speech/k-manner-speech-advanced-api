from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from app.schemas.common import JobType
from app.services.jobs import get_job_queue_name

# 단일 출처는 app.services.jobs 다. worker 는 그 표를 그대로 쓴다.
JOB_QUEUE_NAMES: dict[JobType, str] = {
    job_type: get_job_queue_name(job_type) for job_type in JobType
}


class ProviderFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float | None


class RetryPlanner:
    def __init__(
        self,
        maximum_attempts: int,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        if maximum_attempts <= 0:
            raise ValueError("maximum_attempts must be positive")
        self._maximum_attempts = maximum_attempts
        self._jitter = jitter or (lambda upper: random.uniform(0, upper))

    def decide(
        self,
        attempt_count: int,
        deadline_at: datetime,
        now: datetime,
        failure: ProviderFailure,
    ) -> RetryDecision:
        if not failure.retryable or attempt_count >= self._maximum_attempts:
            return RetryDecision(False, None)
        exponential_upper = float(2 ** max(0, attempt_count - 1))
        delay = (
            failure.retry_after_seconds
            if failure.retry_after_seconds is not None
            else self._jitter(exponential_upper)
        )
        if delay < 0 or delay >= (deadline_at - now).total_seconds():
            return RetryDecision(False, None)
        return RetryDecision(True, delay)


Parsed = TypeVar("Parsed")


class StructuredOutputRepair(Generic[Parsed]):
    def __init__(
        self,
        parser: Callable[[str], Parsed],
        repair: Callable[[str, str], str],
    ) -> None:
        self._parser = parser
        self._repair = repair

    def parse(self, payload: str) -> Parsed:
        try:
            return self._parser(payload)
        except ValueError as first_error:
            repaired = self._repair(payload, str(first_error)[:500])
        try:
            return self._parser(repaired)
        except ValueError as second_error:
            raise ProviderFailure(
                "PROVIDER_SCHEMA_INVALID",
                retryable=False,
            ) from second_error
