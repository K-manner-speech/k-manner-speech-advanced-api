from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, get_authenticated_user
from app.core.dependencies import get_session
from app.repositories.feedback import FeedbackRepository
from app.schemas.feedback import FeedbackResponse
from app.schemas.jobs import DomainJobAccepted
from app.services.feedback import FeedbackService, SqlFeedbackService

router = APIRouter(tags=["feedback"])


def get_feedback_service(
    session: Annotated[Session, Depends(get_session)],
) -> FeedbackService:
    return SqlFeedbackService(FeedbackRepository(session))


@router.get(
    "/messages/{message_id}/feedback",
    operation_id="message_feedback.get",
    response_model=FeedbackResponse,
)
def get_feedback(
    message_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[FeedbackService, Depends(get_feedback_service)],
) -> FeedbackResponse:
    return service.get_feedback(user.id, message_id)


@router.post(
    "/messages/{message_id}/feedback/retry",
    operation_id="message_feedback.retry",
    response_model=DomainJobAccepted,
    status_code=202,
)
def retry_feedback(
    message_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[FeedbackService, Depends(get_feedback_service)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> DomainJobAccepted:
    return service.retry_feedback(user.id, message_id, idempotency_key)


@router.post(
    "/messages/{message_id}/emotion/retry",
    operation_id="message_emotion.retry",
    response_model=DomainJobAccepted,
    status_code=202,
)
def retry_emotion(
    message_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[FeedbackService, Depends(get_feedback_service)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> DomainJobAccepted:
    return service.retry_emotion(user.id, message_id, idempotency_key)
