from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.adapters.storage import SupabaseStorageSigner
from app.core.auth import AuthenticatedUser, get_authenticated_user
from app.core.config import AppSettings
from app.core.dependencies import get_session, get_session_factory, get_settings
from app.core.errors import ApiError
from app.repositories.media import MediaRepository
from app.schemas.jobs import DomainJobAccepted
from app.schemas.media import AudioAccessResponse, RepeatRequest
from app.schemas.rooms import MessageAccepted
from app.services.idempotency import IdempotencyRepository
from app.services.media import MediaService, SqlMediaService
from app.services.tts_streaming import iter_tts_pcm, resolve_tts_stream_target

router = APIRouter(tags=["media"])


def get_media_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> MediaService:
    signer = SupabaseStorageSigner(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value()
    )
    return SqlMediaService(
        MediaRepository(session),
        signer,
        settings.user_queue_limit,
        IdempotencyRepository(session),
        settings.idempotency_lease_seconds,
        settings.idempotency_retention_seconds,
    )


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


@router.get(
    "/messages/{message_id}/audio/stream",
    operation_id="message_audio.stream",
    response_class=StreamingResponse,
)
def stream_audio(
    message_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> StreamingResponse:
    session_factory = get_session_factory()
    target = resolve_tts_stream_target(session_factory, user.id, message_id)
    if target is None:
        raise ApiError(404, "AUDIO_NOT_FOUND", "오디오를 찾을 수 없습니다.")
    token = target["processing_token"]
    if token is None:
        raise ApiError(
            409,
            "AUDIO_STREAM_NOT_AVAILABLE",
            "실시간 음성 스트림을 사용할 수 없습니다.",
        )
    return StreamingResponse(
        iter_tts_pcm(session_factory, target["id"], token),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Audio-Format": "s16le",
            "X-Audio-Sample-Rate": "24000",
            "X-Audio-Channels": "1",
        },
    )


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


@router.post(
    "/rooms/{room_id}/voice-messages",
    operation_id="room_voice_message.create",
    response_model=MessageAccepted,
    status_code=202,
)
def create_voice_message(
    room_id: UUID,
    transcript: Annotated[str, Form()],
    audio: Annotated[UploadFile, File()],
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[MediaService, Depends(get_media_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
    current_interview_question_id: Annotated[UUID | None, Form()] = None,
) -> MessageAccepted:
    return service.upload_voice_message(
        user.id,
        room_id,
        transcript,
        current_interview_question_id,
        audio.file.read(10 * 1024 * 1024 + 1),
        audio.content_type or "",
        key,
    )
