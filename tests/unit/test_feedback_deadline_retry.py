from __future__ import annotations

from app.schemas.common import JobType
from worker.sql_queue import _expired_feedback_retry_delay


def test_feedback_deadline_retries_the_first_two_attempts() -> None:
    assert _expired_feedback_retry_delay(JobType.TURN_FEEDBACK, 1, 3) == 1.0
    assert _expired_feedback_retry_delay(JobType.TURN_FEEDBACK, 2, 3) == 2.0


def test_feedback_deadline_fails_after_the_third_attempt() -> None:
    assert _expired_feedback_retry_delay(JobType.TURN_FEEDBACK, 3, 3) is None


def test_deadline_retry_does_not_expand_to_other_job_types() -> None:
    for job_type in JobType:
        if job_type is not JobType.TURN_FEEDBACK:
            assert _expired_feedback_retry_delay(job_type, 1, 3) is None
