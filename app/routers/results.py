from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, get_authenticated_user
from app.core.config import AppSettings
from app.core.dependencies import get_session, get_settings
from app.repositories.results import ResultRepository
from app.schemas.jobs import DomainJobAccepted
from app.schemas.pagination import Page
from app.schemas.results import SessionResult, SessionResultSummary
from app.services.results import ResultService, SqlResultService

router = APIRouter(tags=["results"])


def get_result_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> ResultService:
    return SqlResultService(ResultRepository(session), settings.pagination_limit)


@router.get("/rooms/{room_id}/result", operation_id="room_result.get", response_model=SessionResult)
def get_room_result(
    room_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ResultService, Depends(get_result_service)],
) -> SessionResult:
    return service.get_room_result(user.id, room_id)


@router.post(
    "/rooms/{room_id}/result/retry",
    operation_id="room_result.retry",
    response_model=DomainJobAccepted,
    status_code=202,
)
def retry_room_result(
    room_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ResultService, Depends(get_result_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> DomainJobAccepted:
    return service.retry_room_result(user.id, room_id, key)


@router.get("/results", operation_id="result.list", response_model=Page[SessionResultSummary])
def list_results(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ResultService, Depends(get_result_service)],
    cursor: str | None = None,
    limit: Annotated[int | None, Query(gt=0)] = None,
) -> Page[SessionResultSummary]:
    return service.list_results(user.id, cursor, limit)


@router.get("/results/{result_id}", operation_id="result.get", response_model=SessionResult)
def get_result(
    result_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ResultService, Depends(get_result_service)],
) -> SessionResult:
    return service.get_result(user.id, result_id)


@router.delete("/results/{result_id}", operation_id="result.delete", status_code=204)
def delete_result(
    result_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[ResultService, Depends(get_result_service)],
    key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> Response:
    service.delete_result(user.id, result_id, key)
    return Response(status_code=204)
