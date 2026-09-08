from uuid import uuid4

from worker.tts_metrics import TTSMetrics


def test_success_event_contains_stage_timings_and_derived_realtime_factor() -> None:
    metrics = TTSMetrics(
        job_id=uuid4(),
        message_audio_id=uuid4(),
        text_chars=24,
        queue_wait_ms=125.4,
        provider_first_chunk_ms=810.2,
        provider_total_ms=2410.7,
        db_write_ms=315.1,
        storage_upload_ms=220.5,
        end_to_end_ms=3110.8,
        audio_duration_ms=4000,
        chunk_count=8,
        attempt_count=1,
        result="success",
    )

    event = metrics.as_event()

    assert event["event"] == "tts_performance"
    assert event["realtime_factor"] == 0.603
    assert event["result"] == "success"
    assert event["error_code"] is None


def test_failure_event_records_attempt_and_code_without_sensitive_payload() -> None:
    metrics = TTSMetrics.failure(
        job_id=uuid4(),
        message_audio_id=uuid4(),
        text_chars=19,
        queue_wait_ms=50,
        attempt_count=2,
        error_code="AI_PROVIDER_TIMEOUT",
    )

    event = metrics.as_event()

    assert event["attempt_count"] == 2
    assert event["result"] == "failure"
    assert event["error_code"] == "AI_PROVIDER_TIMEOUT"
    assert not ({"text", "token", "pcm", "storage_path", "user_id"} & event.keys())


def test_negative_durations_are_normalized_to_zero() -> None:
    metrics = TTSMetrics.failure(
        job_id=uuid4(),
        message_audio_id=uuid4(),
        text_chars=0,
        queue_wait_ms=-1,
        attempt_count=1,
        error_code="JOB_DEADLINE_EXCEEDED",
    )

    assert metrics.as_event()["queue_wait_ms"] == 0.0
