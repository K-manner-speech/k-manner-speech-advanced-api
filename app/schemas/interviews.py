from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import ContractModel
from app.schemas.common import DomainRef, JobRef

DocumentType = Literal["resume", "portfolio", "self_introduction"]


class InterviewSetupCreateRequest(ContractModel):
    desired_role: str = Field(min_length=1, max_length=200)
    application_type: str | None = Field(default=None, max_length=100)


class InterviewSetup(ContractModel):
    id: UUID
    desired_role: str
    application_type: str | None
    status: str
    preparation_progress: int


class InterviewDocument(ContractModel):
    id: UUID
    setup_id: UUID
    document_type: DocumentType
    original_filename: str
    mime_type: str
    size_bytes: int
    version: int
    current: bool
    upload_status: str
    analysis_status: str
    uploaded_at: datetime


class AnalysisAccepted(ContractModel):
    analysis_id: UUID
    document_id: UUID
    document_version: int
    job: JobRef


class SafeDomainError(ContractModel):
    code: str
    retryable: bool


class InterviewAnalysis(ContractModel):
    id: UUID
    document_id: UUID
    document_version: int
    status: str
    extracted_sections: dict[str, Any]
    source_refs: list[DomainRef]
    error: SafeDomainError | None


class InterviewConfigurationGenerateRequest(ContractModel):
    setup_id: UUID
    analysis_ids: list[UUID] = Field(min_length=1)
    question_count: int = Field(ge=1, le=10)


class InterviewConfigurationRegenerateRequest(ContractModel):
    question_count: int | None = Field(default=None, ge=1, le=10)


class ConfigurationAccepted(ContractModel):
    configuration_id: UUID
    version_no: int
    job: JobRef


class InterviewConfiguration(ContractModel):
    id: UUID
    setup_id: UUID
    version_no: int
    status: str
    document_version_snapshot: dict[str, Any]
    analysis_ids: list[UUID]
    question_count: int
    error: SafeDomainError | None


class InterviewQuestion(ContractModel):
    id: UUID
    sequence: int
    text: str
    type: str
    required: bool
    source_refs: list[dict[str, Any]]
    evaluation_focus: list[Any]


class InterviewQuestionList(ContractModel):
    configuration_id: UUID
    version_no: int
    status: str
    questions: list[InterviewQuestion]
