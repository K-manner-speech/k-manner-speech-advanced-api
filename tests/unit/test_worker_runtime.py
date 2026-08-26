from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.schemas.common import JobType
from worker.runtime import ProviderFailure, RetryPlanner, StructuredOutputRepair


def test_retry_planner_uses_retry_after_inside_deadline() -> None:
    now = datetime.now(UTC)
    planner = RetryPlanner(maximum_attempts=3, jitter=lambda _upper: 0.25)

    decision = planner.decide(
        attempt_count=1,
        deadline_at=now + timedelta(seconds=20),
        now=now,
        failure=ProviderFailure("RATE_LIMITED", retryable=True, retry_after_seconds=3),
    )

    assert decision.should_retry is True
    assert decision.delay_seconds == 3


def test_retry_planner_fails_when_attempts_exhausted_or_deadline_wins() -> None:
    now = datetime.now(UTC)
    planner = RetryPlanner(maximum_attempts=3, jitter=lambda _upper: 1.0)
    failure = ProviderFailure("PROVIDER_DOWN", retryable=True)

    exhausted = planner.decide(3, now + timedelta(seconds=20), now, failure)
    late = planner.decide(1, now + timedelta(milliseconds=100), now, failure)

    assert exhausted.should_retry is False
    assert late.should_retry is False


def test_non_retryable_provider_error_never_retries() -> None:
    now = datetime.now(UTC)
    decision = RetryPlanner(3).decide(
        1,
        now + timedelta(seconds=20),
        now,
        ProviderFailure("INVALID_INPUT", retryable=False),
    )

    assert decision.should_retry is False


def test_structured_output_repair_runs_exactly_once() -> None:
    calls: list[str] = []

    def parse(payload: str) -> int:
        if payload != "valid":
            raise ValueError("schema")
        return 7

    def repair(_payload: str, _summary: str) -> str:
        calls.append("repair")
        return "valid"

    assert StructuredOutputRepair(parse, repair).parse("invalid") == 7
    assert calls == ["repair"]


def test_structured_output_second_failure_is_terminal() -> None:
    repair = StructuredOutputRepair(
        lambda _payload: (_ for _ in ()).throw(ValueError("schema")),
        lambda _payload, _summary: "still-invalid",
    )

    try:
        repair.parse("invalid")
    except ProviderFailure as error:
        assert error.code == "PROVIDER_SCHEMA_INVALID"
        assert error.retryable is False
    else:
        raise AssertionError("second schema failure must be terminal")


def test_all_job_types_have_queue_mapping() -> None:
    from worker.runtime import JOB_QUEUE_NAMES

    assert set(JOB_QUEUE_NAMES) == set(JobType)
    assert JOB_QUEUE_NAMES[JobType.CONVERSATION_TEXT] == "conversation_text"
    assert JOB_QUEUE_NAMES[JobType.TTS_GENERATION] == "interactive_ai"
    assert JOB_QUEUE_NAMES[JobType.INTERVIEW_DOCUMENT_ANALYSIS] == "document_analysis"
