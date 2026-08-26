from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.adapters.storage import SupabaseStorageSigner
from app.core.auth import AuthenticatedUser, get_authenticated_user
from app.core.config import AppSettings
from app.core.dependencies import get_session, get_settings
from app.repositories.interviews import InterviewRepository
from app.schemas.interviews import (
    AnalysisAccepted,
    ConfigurationAccepted,
    InterviewAnalysis,
    InterviewConfiguration,
    InterviewConfigurationGenerateRequest,
    InterviewConfigurationRegenerateRequest,
    InterviewDocument,
    InterviewQuestionList,
    InterviewSetup,
    InterviewSetupCreateRequest,
)
from app.schemas.pagination import Page
from app.schemas.rooms import Room
from app.services.idempotency import IdempotencyRepository
from app.services.interviews import MAX_DOCUMENT_BYTES, SqlInterviewService

router = APIRouter(tags=["interviews"])


def get_interview_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> SqlInterviewService:
    storage = SupabaseStorageSigner(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value()
    )
    return SqlInterviewService(
        InterviewRepository(session),
        storage,
        settings.pagination_limit,
        settings.document_min_text_chars,
        IdempotencyRepository(session),
        settings.idempotency_lease_seconds,
        settings.idempotency_retention_seconds,
    )


@router.post(
    "/interview-setups",
    operation_id="interview_setup.create",
    response_model=InterviewSetup,
    status_code=201,
)
def create_setup(
    request: InterviewSetupCreateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> InterviewSetup:
    return service.create_setup(user.id, request, key)


async def _read_upload(file: UploadFile) -> tuple[str, str, bytes]:
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    return file.filename or "document", file.content_type or "application/octet-stream", content


@router.post(
    "/interview-documents",
    operation_id="interview_document.create",
    response_model=InterviewDocument,
    status_code=201,
)
async def create_document(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    setup_id: Annotated[UUID, Form()],
    document_type: Annotated[Literal["resume", "portfolio", "self_introduction"], Form()],
    file: Annotated[UploadFile, File()],
) -> InterviewDocument:
    filename, content_type, content = await _read_upload(file)
    return service.upload_document(
        user.id, setup_id, document_type, filename, content_type, content, key
    )


@router.get(
    "/interview-documents",
    operation_id="interview_document.list",
    response_model=Page[InterviewDocument],
)
def list_documents(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
    cursor: str | None = None,
    limit: Annotated[int | None, Query(gt=0)] = None,
    document_type: Literal["resume", "portfolio", "self_introduction"] | None = None,
) -> Page[InterviewDocument]:
    return service.list_documents(user.id, cursor, limit, document_type)


@router.get(
    "/interview-documents/{document_id}",
    operation_id="interview_document.get",
    response_model=InterviewDocument,
)
def get_document(
    document_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
) -> InterviewDocument:
    return service.get_document(user.id, document_id)


@router.post(
    "/interview-documents/{document_id}/analyze",
    operation_id="interview_document.analyze",
    response_model=AnalysisAccepted,
    status_code=202,
)
def analyze_document(
    document_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> AnalysisAccepted:
    return service.analyze_document(user.id, document_id, key)


@router.post(
    "/interview-documents/{document_id}/replace",
    operation_id="interview_document.replace",
    response_model=InterviewDocument,
    status_code=201,
)
async def replace_document(
    document_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    setup_id: Annotated[UUID, Form()],
    document_type: Annotated[Literal["resume", "portfolio", "self_introduction"], Form()],
    file: Annotated[UploadFile, File()],
) -> InterviewDocument:
    filename, content_type, content = await _read_upload(file)
    return service.upload_document(
        user.id,
        setup_id,
        document_type,
        filename,
        content_type,
        content,
        key,
        document_id,
    )


@router.delete(
    "/interview-documents/{document_id}",
    operation_id="interview_document.delete",
    status_code=204,
)
def delete_document(
    document_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> Response:
    service.delete_document(user.id, document_id, key)
    return Response(status_code=204)


@router.get(
    "/interview-analyses/{analysis_id}",
    operation_id="interview_analysis.get",
    response_model=InterviewAnalysis,
)
def get_analysis(
    analysis_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
) -> InterviewAnalysis:
    return service.get_analysis(user.id, analysis_id)


@router.post(
    "/interview-configurations",
    operation_id="interview_configuration.generate",
    response_model=ConfigurationAccepted,
    status_code=202,
)
def generate_configuration(
    request: InterviewConfigurationGenerateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> ConfigurationAccepted:
    return service.generate_configuration(user.id, request, key)


@router.get(
    "/interview-configurations/{configuration_id}",
    operation_id="interview_configuration.get",
    response_model=InterviewConfiguration,
)
def get_configuration(
    configuration_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
) -> InterviewConfiguration:
    return service.get_configuration(user.id, configuration_id)


@router.get(
    "/interview-configurations/{configuration_id}/questions",
    operation_id="interview_question.list",
    response_model=InterviewQuestionList,
)
def list_questions(
    configuration_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
) -> InterviewQuestionList:
    return service.list_questions(user.id, configuration_id)


@router.post(
    "/interview-configurations/{configuration_id}/regenerate",
    operation_id="interview_configuration.regenerate",
    response_model=ConfigurationAccepted,
    status_code=202,
)
def regenerate_configuration(
    configuration_id: UUID,
    request: InterviewConfigurationRegenerateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> ConfigurationAccepted:
    return service.regenerate_configuration(user.id, configuration_id, request, key)


@router.post(
    "/interview-configurations/{configuration_id}/practice-room",
    operation_id="interview_practice_room.create",
    response_model=Room,
    status_code=201,
)
def create_practice_room(
    configuration_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[SqlInterviewService, Depends(get_interview_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> Room:
    return service.create_practice_room(user.id, configuration_id, key)
