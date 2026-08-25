from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.adapters.storage import SupabaseStorageSigner
from app.core.auth import AuthenticatedUser, get_authenticated_user
from app.core.config import AppSettings
from app.core.dependencies import get_session, get_settings
from app.repositories.media import MediaRepository
from app.schemas.jobs import DomainJobAccepted
from app.schemas.media import AudioAccessResponse, RepeatRequest
from app.schemas.rooms import MessageAccepted
from app.services.media import MediaService, SqlMediaService

router = APIRouter(tags=["media"])


def get_media_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> MediaService:
    signer = SupabaseStorageSigner(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value()
    )
    return SqlMediaService(MediaRepository(session), signer, settings.user_queue_limit)


@router.post(
    "/messages/{message_id}/tts/retry",
    operation_id="message_tts.retry",
    response_model=DomainJobAccepted,
    status_code=202,
)
def retry_tts(
    message_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[MediaService, Depends(get_media_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> DomainJobAccepted:
    return service.retry_tts(user.id, message_id, key)


@router.get(
    "/messages/{message_id}/audio",
    operation_id="message_audio.get",
    response_model=AudioAccessResponse,
)
def get_audio(
    message_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[MediaService, Depends(get_media_service)],
) -> AudioAccessResponse:
    return service.get_audio(user.id, message_id)


@router.post(
    "/messages/{message_id}/repeat",
    operation_id="message_repeat.create",
    response_model=MessageAccepted,
    status_code=202,
)
def repeat(
    message_id: UUID,
    request: RepeatRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[MediaService, Depends(get_media_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> MessageAccepted:
    return service.repeat(user.id, message_id, request, key)
