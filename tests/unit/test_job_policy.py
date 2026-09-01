import pytest

from app.schemas.common import JobStatus, JobType
from app.services.jobs import get_job_execution_policy, validate_job_transition


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    [
        (JobStatus.QUEUED, JobStatus.PROCESSING),
        (JobStatus.QUEUED, JobStatus.CANCELLED),
        (JobStatus.PROCESSING, JobStatus.QUEUED),
        (JobStatus.PROCESSING, JobStatus.SUCCEEDED),
        (JobStatus.PROCESSING, JobStatus.FAILED),
        (JobStatus.PROCESSING, JobStatus.CANCELLED),
    ],
)
def test_documented_job_transitions_are_allowed(
    current_status: JobStatus,
    next_status: JobStatus,
) -> None:
    validate_job_transition(current_status, next_status)


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    [
        (JobStatus.QUEUED, JobStatus.SUCCEEDED),
        (JobStatus.SUCCEEDED, JobStatus.PROCESSING),
        (JobStatus.FAILED, JobStatus.QUEUED),
        (JobStatus.CANCELLED, JobStatus.PROCESSING),
    ],
)
def test_undocumented_or_terminal_job_transitions_are_rejected(
    current_status: JobStatus,
    next_status: JobStatus,
) -> None:
    with pytest.raises(ValueError, match="job transition"):
        validate_job_transition(current_status, next_status)


@pytest.mark.parametrize(
    ("job_type", "deadline_seconds"),
    [
        (JobType.CONVERSATION_TEXT, 45),
        (JobType.EMOTION_ANALYSIS, 15),
        (JobType.TURN_FEEDBACK, 30),
        (JobType.TTS_GENERATION, 45),
        (JobType.INTERVIEW_DOCUMENT_ANALYSIS, 60),
        (JobType.INTERVIEW_CONFIGURATION_GENERATION, 180),
        (JobType.SESSION_RESULT_GENERATION, 180),
    ],
)
def test_job_execution_policy_uses_fixed_deadline_and_attempts(
    job_type: JobType,
    deadline_seconds: int,
) -> None:
    policy = get_job_execution_policy(job_type)

    assert policy.deadline_seconds == deadline_seconds
    assert policy.maximum_attempts == 3


def test_job_execution_policy_has_no_unknown_fallback() -> None:
    with pytest.raises(ValueError, match="unknown job type"):
        get_job_execution_policy("unknown")
