from dataclasses import dataclass

from app.schemas.common import JobStatus, JobType


@dataclass(frozen=True, slots=True)
class JobExecutionPolicy:
    deadline_seconds: int
    maximum_attempts: int


# 잡을 어느 queue 로 보낼지의 단일 출처. 발행(API)과 소비(worker)가 같은 표를
# 보게 해서, queue 를 옮길 때 한쪽만 고쳐 잡이 붕 뜨는 일을 막는다.
_QUEUE_NAMES: dict[JobType, str] = {
    JobType.CONVERSATION_TEXT: "conversation_text",
    JobType.EMOTION_ANALYSIS: "interactive_ai",
    JobType.TTS_GENERATION: "interactive_ai",
    JobType.TURN_FEEDBACK: "evaluation_ai",
    JobType.INTERVIEW_DOCUMENT_ANALYSIS: "document_analysis",
    JobType.INTERVIEW_CONFIGURATION_GENERATION: "document_analysis",
    JobType.SESSION_RESULT_GENERATION: "evaluation_ai",
    JobType.SCENARIO_GOAL_PROGRESS: "evaluation_ai",
}

# 잡이 결과를 쓸 대상 행을 가리키는 processing_jobs 컬럼.
_TARGET_COLUMNS: dict[JobType, str] = {
    JobType.CONVERSATION_TEXT: "message_ai_processing_id",
    JobType.EMOTION_ANALYSIS: "message_emotion_analysis_id",
    JobType.TTS_GENERATION: "message_audio_id",
    JobType.TURN_FEEDBACK: "turn_feedback_id",
    JobType.INTERVIEW_DOCUMENT_ANALYSIS: "interview_document_analysis_id",
    JobType.INTERVIEW_CONFIGURATION_GENERATION: "interview_configuration_id",
    JobType.SESSION_RESULT_GENERATION: "session_result_id",
    JobType.SCENARIO_GOAL_PROGRESS: "room_goal_evaluation_id",
}

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
    # 판정 자체는 10초 안팎이지만 deadline 은 job 생성 시점부터 흐른다. queue
    # 대기와 provider timeout(30초)을 모두 덮지 못하면 성공한 응답도 이미
    # 죽은 job 에 도착한다.
    JobType.SCENARIO_GOAL_PROGRESS: 60,
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


def get_job_target_columns() -> frozenset[str]:
    return frozenset(_TARGET_COLUMNS.values())


def get_job_target_column(job_type: JobType | str) -> str:
    try:
        normalized_job_type = JobType(job_type)
    except ValueError as error:
        raise ValueError(f"unknown job type: {job_type}") from error

    return _TARGET_COLUMNS[normalized_job_type]


def get_job_queue_name(job_type: JobType | str) -> str:
    try:
        normalized_job_type = JobType(job_type)
    except ValueError as error:
        raise ValueError(f"unknown job type: {job_type}") from error

    return _QUEUE_NAMES[normalized_job_type]


def get_job_execution_policy(job_type: JobType | str) -> JobExecutionPolicy:
    try:
        normalized_job_type = JobType(job_type)
    except ValueError as error:
        raise ValueError(f"unknown job type: {job_type}") from error

    return JobExecutionPolicy(
        deadline_seconds=_DEADLINES_SECONDS[normalized_job_type],
        maximum_attempts=_MAXIMUM_ATTEMPTS,
    )
