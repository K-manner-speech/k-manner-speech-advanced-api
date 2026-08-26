from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.schemas.common import JobType


class JobHandler(Protocol):
    def handle(self, item: object) -> object: ...


class HandlerRegistry:
    def __init__(self, handlers: Mapping[JobType, JobHandler]) -> None:
        missing = [job_type.value for job_type in JobType if job_type not in handlers]
        if missing:
            raise ValueError(f"missing handlers: {', '.join(missing)}")
        self._handlers = dict(handlers)

    def get(self, job_type: JobType) -> JobHandler:
        return self._handlers[job_type]
