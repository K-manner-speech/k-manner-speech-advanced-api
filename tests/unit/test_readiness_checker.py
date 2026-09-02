from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any

from app.core.readiness import DatabaseReadinessChecker


class Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value


class Connection:
    def __init__(self, values: list[Any]) -> None:
        self.values = iter(values)

    def execute(self, statement: Any, parameters: Any = None) -> Result:
        return Result(next(self.values))


class Engine:
    def __init__(self, values: list[Any]) -> None:
        self.connection = Connection(values)

    @contextmanager
    def connect(self) -> Any:
        yield self.connection


def test_readiness_requires_fresh_heartbeat_for_each_base_queue() -> None:
    checker = DatabaseReadinessChecker(
        Engine([1, 2, 8, 8, 4]),  # type: ignore[arg-type]
        [
            "conversation_text",
            "conversation_text_dlq",
            "interactive_ai",
            "interactive_ai_dlq",
            "evaluation_ai",
            "evaluation_ai_dlq",
            "document_analysis",
            "document_analysis_dlq",
        ],
        ["conversation_text", "interactive_ai", "evaluation_ai", "document_analysis"],
        worker_heartbeat_ttl_seconds=30,
    )

    report = asyncio.run(checker.check())

    assert report.database is True
    assert report.required_extensions is True
    assert report.pgmq_queues is True
    assert report.timeout_policies is True
    assert report.worker_heartbeat is True


def test_readiness_fails_when_one_queue_has_no_fresh_worker() -> None:
    checker = DatabaseReadinessChecker(
        Engine([1, 2, 6, 7, 2]),  # type: ignore[arg-type]
        [
            "conversation_text",
            "conversation_text_dlq",
            "interactive_ai",
            "interactive_ai_dlq",
            "document_analysis",
            "document_analysis_dlq",
        ],
        ["conversation_text", "interactive_ai", "document_analysis"],
        worker_heartbeat_ttl_seconds=30,
    )

    report = asyncio.run(checker.check())

    assert report.worker_heartbeat is False


def test_readiness_checks_only_configured_required_worker_queues() -> None:
    checker = DatabaseReadinessChecker(
        Engine([1, 2, 6, 7, 1]),  # type: ignore[arg-type]
        [
            "conversation_text",
            "conversation_text_dlq",
            "interactive_ai",
            "interactive_ai_dlq",
            "document_analysis",
            "document_analysis_dlq",
        ],
        ["document_analysis"],
        worker_heartbeat_ttl_seconds=30,
    )

    report = asyncio.run(checker.check())

    assert report.worker_heartbeat is True, "AC-T2-REQUIRED-WORKERS"
