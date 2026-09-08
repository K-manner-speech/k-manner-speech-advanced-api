from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import ContractModel
from app.schemas.common import DomainRef, JobRef

DocumentType = Literal["resume", "portfolio", "self_introduction"]
# 질문 깊이를 이 값으로 조절하므로 아무 문자열이나 받으면 안 된다.
ApplicationType = Literal["신입", "경력", "인턴"]


class InterviewSetupCreateRequest(ContractModel):
    desired_role: str = Field(min_length=1, max_length=200)
    application_type: ApplicationType | None = None


class InterviewSetup(ContractModel):
    id: UUID
    desired_role: str
    # 예전 데이터에는 목록 밖의 값이 남아 있어 응답 타입은 넓게 둔다.
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
