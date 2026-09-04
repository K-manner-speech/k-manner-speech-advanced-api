from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.adapters.storage import StorageObjectStore
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
from app.services.idempotency import (
    IdempotencyRepository,
    request_fingerprint,
    validate_client_request_id,
)
from app.services.jobs import get_job_execution_policy

ROOM_CREATE_SCOPE = "room.create"
ROOM_DELETE_SCOPE = "room.delete"


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
    def complete_interview(self, user_id: UUID, room_id: UUID) -> Room: ...
    def complete_practice(self, user_id: UUID, room_id: UUID) -> Room: ...
    def continue_after_goal(self, user_id: UUID, room_id: UUID) -> Room: ...
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
        idempotency: IdempotencyRepository | None = None,
        idempotency_lease_seconds: int = 30,
        idempotency_retention_seconds: int = 86400,
        storage: StorageObjectStore | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._maximum_page_limit = maximum_page_limit
        self._user_queue_limit = user_queue_limit
        self._idempotency = idempotency
        self._idempotency_lease_seconds = idempotency_lease_seconds
        self._idempotency_retention_seconds = idempotency_retention_seconds

    def create_room(
        self, user_id: UUID, request: RoomCreateRequest, idempotency_key: UUID
    ) -> tuple[Room, bool]:
        claim = None
        if self._idempotency is not None:
            claim = self._idempotency.claim(
                user_id,
                ROOM_CREATE_SCOPE,
                idempotency_key,
                request_fingerprint(request.model_dump(mode="json")),
                self._idempotency_lease_seconds,
                self._idempotency_retention_seconds,
            )
            if claim.kind == "replay":
                assert claim.response_body is not None
                return Room.model_validate(claim.response_body), False
        existing = self._repository.find_active_room(user_id, request)
        if existing is not None:
            if (
                self._idempotency is not None
                and claim is not None
                and claim.claim_token is not None
            ):
                response = Room.model_validate(existing)
                self._idempotency.complete(
                    user_id,
                    ROOM_CREATE_SCOPE,
                    idempotency_key,
                    claim.claim_token,
                    200,
                    response.model_dump(mode="json"),
                    "v1",
                    self._idempotency_retention_seconds,
                )
                self._repository.commit()
            return Room.model_validate(existing), False
        catalog = self._repository.validate_catalog(request)
        if catalog is None:
            raise ApiError(422, "INVALID_CATALOG_COMBINATION", "연습 조합이 유효하지 않습니다.")
        row = self._repository.create_room(user_id, request, catalog)
        room = Room.model_validate(row)
        if self._idempotency is not None and claim is not None and claim.claim_token is not None:
            self._idempotency.complete(
                user_id,
                ROOM_CREATE_SCOPE,
                idempotency_key,
                claim.claim_token,
                201,
                room.model_dump(mode="json"),
                "v1",
                self._idempotency_retention_seconds,
            )
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
        claim = None
        if self._idempotency is not None:
            claim = self._idempotency.claim(
                user_id,
                ROOM_DELETE_SCOPE,
                idempotency_key,
                request_fingerprint({"room_id": str(room_id)}),
                self._idempotency_lease_seconds,
                self._idempotency_retention_seconds,
            )
            if claim.kind == "replay":
                return
        if self._repository.get_room(user_id, room_id) is None:
            raise ApiError(404, "ROOM_NOT_FOUND", "대화방을 찾을 수 없습니다.")
        # 방이 사라지면 message_audio 레코드도 함께 지워져 경로를 찾을 수 없으므로
        # 삭제 전에 목록을 확보하고 Storage를 먼저 정리한다. 일부 파일만 지워진 뒤
        # 실패해도 Storage DELETE는 missing object를 성공으로 처리하므로 재시도할 수 있다.
        storage_paths = (
            self._repository.list_room_storage_paths(user_id, room_id)
            if self._storage is not None
            else []
        )
        # claim과 삭제 대상 목록을 먼저 확정해 외부 Storage 호출 중에는 DB
        # 트랜잭션을 열어 두지 않는다. 실패 시 persisted claim을 retryable로 바꿀 수 있다.
        self._repository.commit()
        try:
            if self._storage is not None:
                for path in storage_paths:
                    self._storage.delete("message-audio", path)
        except RuntimeError as error:
            self._repository.rollback()
            if (
                self._idempotency is not None
                and claim is not None
                and claim.claim_token is not None
            ):
                self._idempotency.fail_retryable(
                    user_id,
                    ROOM_DELETE_SCOPE,
                    idempotency_key,
                    claim.claim_token,
                    "ROOM_STORAGE_DELETE_FAILED",
                    self._idempotency_retention_seconds,
                )
                self._repository.commit()
            raise ApiError(
                503,
                "ROOM_STORAGE_DELETE_FAILED",
                "대화방의 음성 파일을 삭제하지 못했습니다.",
                retryable=True,
            ) from error
        if not self._repository.delete_room(user_id, room_id):
            raise ApiError(404, "ROOM_NOT_FOUND", "대화방을 찾을 수 없습니다.")
        if (
            self._idempotency is not None
            and claim is not None
            and claim.claim_token is not None
        ):
            self._idempotency.complete(
                user_id,
                ROOM_DELETE_SCOPE,
                idempotency_key,
                claim.claim_token,
                204,
                None,
                "v1",
                self._idempotency_retention_seconds,
            )
        self._repository.commit()

    def complete_interview(self, user_id: UUID, room_id: UUID) -> Room:
        row = self._repository.complete_interview(
            user_id,
            room_id,
            get_job_execution_policy("session_result_generation").deadline_seconds,
        )
        if row is None:
            raise ApiError(
                409,
                "INTERVIEW_NOT_READY_TO_END",
                "아직 수동으로 종료할 수 있는 면접 상태가 아닙니다.",
            )
        self._repository.commit()
        return Room.model_validate(row)

    def complete_practice(self, user_id: UUID, room_id: UUID) -> Room:
        row = self._repository.complete_practice(
            user_id,
            room_id,
            get_job_execution_policy("session_result_generation").deadline_seconds,
        )
        if row is None:
            raise ApiError(
                409,
                "ROOM_NOT_ACTIVE",
                "종료할 수 있는 연습이 아닙니다.",
            )
        self._repository.commit()
        return Room.model_validate(row)

    def continue_after_goal(self, user_id: UUID, room_id: UUID) -> Room:
        row = self._repository.dismiss_goal_prompt(user_id, room_id)
        if row is None:
            raise ApiError(
                409,
                "GOAL_PROMPT_NOT_PENDING",
                "목표 달성 안내가 표시된 상태가 아닙니다.",
            )
        self._repository.commit()
        return Room.model_validate(row)

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
        claim = None
        if self._idempotency is not None:
            claim = self._idempotency.claim(
                user_id,
                "room_message.create",
                idempotency_key,
                request_fingerprint(
                    {"room_id": room_id, "request": request.model_dump(mode="json")}
                ),
                self._idempotency_lease_seconds,
                self._idempotency_retention_seconds,
            )
            if claim.kind == "replay":
                assert claim.response_body is not None
                return MessageAccepted.model_validate(claim.response_body)
        policy = get_job_execution_policy("conversation_text")
        try:
            message_row, job_row = self._repository.create_message_and_job(
                user_id, room_id, request, policy.deadline_seconds, self._user_queue_limit
            )
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
        response = MessageAccepted(
            message=self._message(message_row),
            job=JobRef(job_id=job_row["id"], type=job_row["type"], status=job_row["status"]),
        )
        if self._idempotency is not None and claim is not None and claim.claim_token is not None:
            self._idempotency.complete(
                user_id,
                "room_message.create",
                idempotency_key,
                claim.claim_token,
                202,
                response.model_dump(mode="json"),
                "v1",
                self._idempotency_retention_seconds,
            )
        self._repository.commit()
        return response

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
