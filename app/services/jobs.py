from dataclasses import dataclass

from app.schemas.common import JobStatus, JobType


@dataclass(frozen=True, slots=True)
class JobExecutionPolicy:
    deadline_seconds: int
    maximum_attempts: int


_MAXIMUM_ATTEMPTS = 3
_DEADLINES_SECONDS: dict[JobType, int] = {
    JobType.CONVERSATION_TEXT: 45,
    JobType.EMOTION_ANALYSIS: 15,
    JobType.TURN_FEEDBACK: 30,
    JobType.TTS_GENERATION: 45,
    JobType.INTERVIEW_DOCUMENT_ANALYSIS: 60,
    JobType.INTERVIEW_CONFIGURATION_GENERATION: 180,
    # 종합 평가는 전체 대화와 면접 근거를 함께 구조화하므로 단일 AI 호출의
    # 60초 제한과 같은 deadline을 쓰면 정상 응답 직전에 reaper가 작업을
    # 실패시킬 수 있다. provider timeout 이후 재시도할 여유까지 확보한다.
    JobType.SESSION_RESULT_GENERATION: 180,
}

_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.PROCESSING, JobStatus.CANCELLED}),
    JobStatus.PROCESSING: frozenset(
        {
            JobStatus.QUEUED,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def validate_job_transition(
    current_status: JobStatus,
    next_status: JobStatus,
) -> None:
    if next_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise ValueError(f"invalid job transition: {current_status.value} -> {next_status.value}")


def get_job_execution_policy(job_type: JobType | str) -> JobExecutionPolicy:
    try:
        normalized_job_type = JobType(job_type)
    except ValueError as error:
        raise ValueError(f"unknown job type: {job_type}") from error

    return JobExecutionPolicy(
        deadline_seconds=_DEADLINES_SECONDS[normalized_job_type],
        maximum_attempts=_MAXIMUM_ATTEMPTS,
    )
