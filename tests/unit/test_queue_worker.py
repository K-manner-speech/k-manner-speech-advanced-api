from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.ai.interfaces import AIProviderError
from app.schemas.common import JobType
from worker.queue import ClaimedJob, QueueMessage, QueueWorker


@dataclass
class FakeRepository:
    item: ClaimedJob | None
    events: list[tuple[str, Any]] = field(default_factory=list)

    def recover_expired(self) -> int:
        self.events.append(("recover_expired", None))
        return 0

    def read_one(self) -> QueueMessage:
        return QueueMessage(3, uuid4())

    def claim(self, _job_id: UUID) -> ClaimedJob | None:
        return self.item

    def complete(self, message: QueueMessage, item: ClaimedJob, output: object) -> bool:
        self.events.append(("complete", output))
        return True

    def retry(
        self,
        message: QueueMessage,
        item: ClaimedJob,
        code: str,
        delay_seconds: float,
    ) -> None:
        self.events.append(("retry", (code, delay_seconds)))

    def fail(self, message: QueueMessage, item: ClaimedJob, code: str) -> None:
        self.events.append(("fail", code))

    def discard(self, message: QueueMessage) -> None:
        self.events.append(("discard", message.message_id))

    def mark_schema_repair(self, item: ClaimedJob) -> None:
        self.events.append(("repair", item.job_id))


class FakeExecutor:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = outputs
        self.repair_flags: list[bool] = []

    def execute(self, _item: ClaimedJob, *, repair: bool = False) -> object:
        self.repair_flags.append(repair)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


def item(attempts: int = 1, repairs: int = 0) -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(),
        job_type=JobType.TURN_FEEDBACK,
        user_id=uuid4(),
        target_id=uuid4(),
        processing_token=uuid4(),
        attempt_count=attempts,
        schema_repair_count=repairs,
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        payload={"text": "답변"},
    )


def test_queue_worker_completes_and_source_ack_is_repository_atomic() -> None:
    repository = FakeRepository(item())
    executor = FakeExecutor([{"ok": True}])

    assert QueueWorker(repository, executor, maximum_attempts=3).run_once() is True
    assert repository.events == [
        ("recover_expired", None),
        ("complete", {"ok": True}),
    ]


def test_queue_worker_discards_stale_claim_without_provider_call() -> None:
    repository = FakeRepository(None)
    executor = FakeExecutor([])

    assert QueueWorker(repository, executor, maximum_attempts=3).run_once() is True
    assert [event[0] for event in repository.events] == ["recover_expired", "discard"]
    assert executor.repair_flags == []


def test_queue_worker_repairs_schema_exactly_once() -> None:
    repository = FakeRepository(item())
    executor = FakeExecutor(
        [
            AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID",
                retryable=False,
                schema_invalid=True,
            ),
            {"repaired": True},
        ]
    )

    QueueWorker(repository, executor, maximum_attempts=3).run_once()

    assert executor.repair_flags == [False, True]
    assert [event[0] for event in repository.events] == [
        "recover_expired",
        "repair",
        "complete",
    ]


def test_queue_worker_retries_transport_failure_and_fails_second_schema_error() -> None:
    retry_repository = FakeRepository(item())
    QueueWorker(
        retry_repository,
        FakeExecutor([AIProviderError("DOWN", retryable=True)]),
        maximum_attempts=3,
        jitter=lambda _upper: 0.1,
    ).run_once()
    assert retry_repository.events[1][0] == "retry"

    schema_repository = FakeRepository(item())
    schema_error = AIProviderError(
        "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
    )
    QueueWorker(
        schema_repository,
        FakeExecutor([schema_error, schema_error]),
        maximum_attempts=3,
    ).run_once()
    assert schema_repository.events[-1] == ("fail", "AI_PROVIDER_SCHEMA_INVALID")


def test_queue_worker_retries_dependency_failure_raised_while_saving() -> None:
    class FailingCompleteRepository(FakeRepository):
        def complete(
            self, message: QueueMessage, item: ClaimedJob, output: object
        ) -> bool:
            raise AIProviderError("STORAGE_UNAVAILABLE", retryable=True)

    repository = FailingCompleteRepository(item())

    QueueWorker(
        repository,
        FakeExecutor([{"wav": True}]),
        maximum_attempts=3,
        jitter=lambda _upper: 0.1,
    ).run_once()

    assert repository.events == [
        ("recover_expired", None),
        ("retry", ("STORAGE_UNAVAILABLE", 0.1)),
    ]
