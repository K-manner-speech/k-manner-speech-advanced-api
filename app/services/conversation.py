from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.core.errors import ApiError
from app.repositories.conversation import (
    ConversationRepository,
    InterviewQuestionModeError,
    InterviewQuestionOrderError,
)
from app.schemas.common import Job, JobError, JobProgress, JobRef
from app.schemas.pagination import Page
from app.schemas.rooms import (
    EmotionSnapshot,
    Message,
    MessageAccepted,
    MessageCreateRequest,
    Room,
    RoomCreateRequest,
    RoomDetail,
    RoomSummary,
)
from app.services.idempotency import validate_client_request_id
from app.services.jobs import get_job_execution_policy


class ConversationService(Protocol):
    def create_room(
        self, user_id: UUID, request: RoomCreateRequest, idempotency_key: UUID
    ) -> tuple[Room, bool]: ...
    def list_rooms(
        self,
        user_id: UUID,
        cursor: str | None,
        limit: int,
        status: str | None,
        practice_type: str | None,
    ) -> Page[RoomSummary]: ...
    def get_room(self, user_id: UUID, room_id: UUID) -> RoomDetail: ...
    def delete_room(self, user_id: UUID, room_id: UUID, idempotency_key: UUID) -> None: ...
    def list_messages(
        self, user_id: UUID, room_id: UUID, cursor: str | None, limit: int
    ) -> Page[Message]: ...
    def create_message(
        self, user_id: UUID, room_id: UUID, request: MessageCreateRequest, idempotency_key: UUID
    ) -> MessageAccepted: ...
    def retry_response(
        self, user_id: UUID, message_id: UUID, idempotency_key: UUID
    ) -> MessageAccepted: ...
    def get_job(self, user_id: UUID, job_id: UUID) -> Job: ...


class SqlConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        maximum_page_limit: int,
        user_queue_limit: int,
    ) -> None:
        self._repository = repository
        self._maximum_page_limit = maximum_page_limit
        self._user_queue_limit = user_queue_limit

    def create_room(
        self, user_id: UUID, request: RoomCreateRequest, idempotency_key: UUID
    ) -> tuple[Room, bool]:
        del idempotency_key
        existing = self._repository.find_active_room(user_id, request)
        if existing is not None:
            return Room.model_validate(existing), False
        catalog = self._repository.validate_catalog(request)
        if catalog is None:
            raise ApiError(422, "INVALID_CATALOG_COMBINATION", "연습 조합이 유효하지 않습니다.")
        row = self._repository.create_room(user_id, request, catalog)
        room = Room.model_validate(row)
        self._repository.commit()
        return room, True

    def _validate_page(self, cursor: str | None, limit: int) -> None:
        if cursor is not None or limit > self._maximum_page_limit:
            raise ApiError(422, "INVALID_PAGE", "페이지 요청이 유효하지 않습니다.")

    def list_rooms(
        self,
        user_id: UUID,
        cursor: str | None,
        limit: int,
        status: str | None,
        practice_type: str | None,
    ) -> Page[RoomSummary]:
        self._validate_page(cursor, limit)
        return Page(
            items=[
                RoomSummary.model_validate(row)
                for row in self._repository.list_rooms(user_id, limit, status, practice_type)
            ],
            next_cursor=None,
        )

    def get_room(self, user_id: UUID, room_id: UUID) -> RoomDetail:
        row = self._repository.get_room(user_id, room_id)
        if row is None:
            raise ApiError(404, "ROOM_NOT_FOUND", "대화방을 찾을 수 없습니다.")
        return RoomDetail.model_validate(row)

    def delete_room(self, user_id: UUID, room_id: UUID, idempotency_key: UUID) -> None:
        del idempotency_key
        if not self._repository.delete_room(user_id, room_id):
            raise ApiError(404, "ROOM_NOT_FOUND", "대화방을 찾을 수 없습니다.")
        self._repository.commit()

    def _message(self, row: dict[str, object]) -> Message:
        status = row.pop("emotion_status", None)
        label = row.pop("emotion_label", None)
        reasoning = row.pop("reasoning", None)
        emotion = None
        if status is not None:
            emotion = EmotionSnapshot(status=status, label=label, reasoning=reasoning)
        return Message.model_validate({**row, "emotion": emotion})

    def list_messages(
        self, user_id: UUID, room_id: UUID, cursor: str | None, limit: int
    ) -> Page[Message]:
        self._validate_page(cursor, limit)
        rows = self._repository.list_messages(user_id, room_id, limit)
        if rows is None:
            raise ApiError(404, "ROOM_NOT_FOUND", "대화방을 찾을 수 없습니다.")
        return Page(items=[self._message(row) for row in rows], next_cursor=None)

    def create_message(
        self, user_id: UUID, room_id: UUID, request: MessageCreateRequest, idempotency_key: UUID
    ) -> MessageAccepted:
        try:
            validate_client_request_id(request.client_request_id, idempotency_key)
        except ValueError as error:
            raise ApiError(
                422,
                "CLIENT_REQUEST_ID_MISMATCH",
                "client_request_id는 Idempotency-Key와 같아야 합니다.",
            ) from error
        policy = get_job_execution_policy("conversation_text")
        try:
            message_row, job_row = self._repository.create_message_and_job(
                user_id, room_id, request, policy.deadline_seconds, self._user_queue_limit
            )
            self._repository.commit()
        except LookupError as error:
            raise ApiError(404, "ROOM_NOT_FOUND", "대화방을 찾을 수 없습니다.") from error
        except RuntimeError as error:
            raise ApiError(409, "ROOM_NOT_ACTIVE", "대화가 진행 중인 상태가 아닙니다.") from error
        except OverflowError as error:
            raise ApiError(
                429, "USER_QUEUE_LIMIT_EXCEEDED", "처리 대기 한도를 초과했습니다.", retryable=True
            ) from error
        except InterviewQuestionModeError as error:
            raise ApiError(
                422,
                "INTERVIEW_QUESTION_MODE_INVALID",
                "현재 연습 유형에 맞는 면접 질문이 필요합니다.",
            ) from error
        except InterviewQuestionOrderError as error:
            raise ApiError(
                409,
                "INTERVIEW_QUESTION_OUT_OF_ORDER",
                "현재 순서의 면접 질문에 먼저 답변해야 합니다.",
            ) from error
        return MessageAccepted(
            message=self._message(message_row),
            job=JobRef(job_id=job_row["id"], type=job_row["type"], status=job_row["status"]),
        )

    def retry_response(
        self, user_id: UUID, message_id: UUID, idempotency_key: UUID
    ) -> MessageAccepted:
        del idempotency_key
        policy = get_job_execution_policy("conversation_text")
        try:
            retried = self._repository.retry_response(
                user_id,
                message_id,
                policy.deadline_seconds,
            )
            if retried is None:
                raise ApiError(404, "MESSAGE_NOT_FOUND", "메시지를 찾을 수 없습니다.")
            message_row, job_row = retried
            self._repository.commit()
        except RuntimeError as error:
            raise ApiError(
                409,
                "RESPONSE_NOT_RETRYABLE",
                "현재 응답은 재시도할 수 없습니다.",
            ) from error
        if retried is None:
            raise ApiError(404, "MESSAGE_NOT_FOUND", "메시지를 찾을 수 없습니다.")
        return MessageAccepted(
            message=self._message(message_row),
            job=JobRef(
                job_id=job_row["id"],
                type=job_row["type"],
                status=job_row["status"],
            ),
        )

    def get_job(self, user_id: UUID, job_id: UUID) -> Job:
        row = self._repository.get_job(user_id, job_id)
        if row is None:
            raise ApiError(404, "JOB_NOT_FOUND", "작업을 찾을 수 없습니다.")
        return Job(
            id=row["id"],
            type=row["type"],
            status=row["status"],
            progress=JobProgress(
                stage=row["progress_stage"],
                completed_units=row["completed_units"],
                total_units=row["total_units"],
            ),
            error=JobError(
                code=row["error_code"], retryable=row["error_retryable"], meta=row["error_meta"]
            )
            if row["error_code"]
            else None,
            result_resource=None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
