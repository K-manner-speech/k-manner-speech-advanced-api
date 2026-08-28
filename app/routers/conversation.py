from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.adapters.storage import SupabaseStorageSigner
from app.core.auth import AuthenticatedUser, get_authenticated_user
from app.core.config import AppSettings
from app.core.dependencies import get_session, get_settings
from app.repositories.conversation import ConversationRepository
from app.schemas.common import Job
from app.schemas.pagination import Page
from app.schemas.rooms import (
    Message,
    MessageAccepted,
    MessageCreateRequest,
    Room,
    RoomCreateRequest,
    RoomDetail,
    RoomSummary,
)
from app.services.conversation import ConversationService, SqlConversationService
from app.services.idempotency import IdempotencyRepository

router = APIRouter(tags=["conversation"])


def get_conversation_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> ConversationService:
    return SqlConversationService(
        ConversationRepository(session),
        settings.pagination_limit,
        settings.user_queue_limit,
        IdempotencyRepository(session),
        settings.idempotency_lease_seconds,
        settings.idempotency_retention_seconds,
        SupabaseStorageSigner(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        ),
    )


@router.post("/rooms", operation_id="room.create", response_model=Room, status_code=201)
def create_room(
    request: RoomCreateRequest,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> Room:
    room, created = service.create_room(user.id, request, idempotency_key)
    response.status_code = 201 if created else 200
    return room


@router.get("/rooms", operation_id="room.list", response_model=Page[RoomSummary])
def list_rooms(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    limit: Annotated[int, Query(gt=0)],
    cursor: str | None = None,
    status: str | None = None,
    practice_type: str | None = None,
) -> Page[RoomSummary]:
    return service.list_rooms(user.id, cursor, limit, status, practice_type)


@router.get("/rooms/{room_id}", operation_id="room.get", response_model=RoomDetail)
def get_room(
    room_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> RoomDetail:
    return service.get_room(user.id, room_id)


@router.delete("/rooms/{room_id}", operation_id="room.delete", status_code=204)
def delete_room(
    room_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> None:
    service.delete_room(user.id, room_id, idempotency_key)


@router.get(
    "/rooms/{room_id}/messages", operation_id="room_message.list", response_model=Page[Message]
)
def list_messages(
    room_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    limit: Annotated[int, Query(gt=0)],
    cursor: str | None = None,
) -> Page[Message]:
    return service.list_messages(user.id, room_id, cursor, limit)


@router.post(
    "/rooms/{room_id}/messages",
    operation_id="room_message.create",
    response_model=MessageAccepted,
    status_code=202,
)
def create_message(
    room_id: UUID,
    request: MessageCreateRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> MessageAccepted:
    return service.create_message(user.id, room_id, request, idempotency_key)


@router.post(
    "/messages/{message_id}/retry-response",
    operation_id="message_response.retry",
    response_model=MessageAccepted,
    status_code=202,
)
def retry_response(
    message_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> MessageAccepted:
    return service.retry_response(user.id, message_id, idempotency_key)


@router.get("/jobs/{job_id}", operation_id="job.get", response_model=Job)
def get_job(
    job_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> Job:
    return service.get_job(user.id, job_id)
