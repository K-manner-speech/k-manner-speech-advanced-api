from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import ContractModel


class JobType(StrEnum):
    CONVERSATION_TEXT = "conversation_text"
    EMOTION_ANALYSIS = "emotion_analysis"
    TTS_GENERATION = "tts_generation"
    TURN_FEEDBACK = "turn_feedback"
    INTERVIEW_DOCUMENT_ANALYSIS = "interview_document_analysis"
    INTERVIEW_CONFIGURATION_GENERATION = "interview_configuration_generation"
    SESSION_RESULT_GENERATION = "session_result_generation"
    SCENARIO_GOAL_PROGRESS = "scenario_goal_progress"


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FieldError(ContractModel):
    field: str
    code: str


class ErrorEnvelope(ContractModel):
    code: str
    message: str
    fields: dict[str, Any] = Field(default_factory=dict)
    field_errors: list[FieldError] = Field(default_factory=list)
    request_id: UUID
    retryable: bool


class JobRef(ContractModel):
    job_id: UUID
    type: JobType
    status: JobStatus

    @model_validator(mode="after")
    def require_queued_status(self) -> JobRef:
        if self.status is not JobStatus.QUEUED:
            raise ValueError("accepted job status must be queued")
        return self


class DomainRef(ContractModel):
    type: str
    id: UUID


class JobProgress(ContractModel):
    stage: str | None
    completed_units: int | None
    total_units: int | None


class JobError(ContractModel):
    code: str
    retryable: bool
    meta: dict[str, Any] | None


_PROCESSING_STAGES: dict[JobType, frozenset[str]] = {
    JobType.CONVERSATION_TEXT: frozenset(
        {"context_preparing", "provider_processing", "saving_response"}
    ),
    JobType.EMOTION_ANALYSIS: frozenset({"provider_processing", "saving_analysis"}),
    JobType.TTS_GENERATION: frozenset({"provider_processing", "storing_audio"}),
    JobType.TURN_FEEDBACK: frozenset({"provider_processing", "saving_feedback"}),
    JobType.INTERVIEW_DOCUMENT_ANALYSIS: frozenset(
        {"extracting_text", "chunking", "embedding", "saving_analysis"}
    ),
    JobType.INTERVIEW_CONFIGURATION_GENERATION: frozenset(
        {"retrieving_evidence", "provider_processing", "saving_configuration"}
    ),
    JobType.SESSION_RESULT_GENERATION: frozenset(
        {"aggregating_evidence", "provider_processing", "saving_result"}
    ),
}


class Job(ContractModel):
    id: UUID
    type: JobType
    status: JobStatus
    progress: JobProgress
    error: JobError | None
    result_resource: DomainRef | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_progress(self) -> Job:
        stage = self.progress.stage
        if self.status is not JobStatus.PROCESSING:
            if stage is not None:
                raise ValueError("queued and terminal jobs cannot report a progress stage")
            return self

        if stage is not None and stage not in _PROCESSING_STAGES[self.type]:
            raise ValueError("progress stage does not belong to the job type")
        return self
