from typing import Protocol
from uuid import UUID

from app.adapters.storage import StorageSigner
from app.core.errors import ApiError
from app.repositories.media import MediaRepository
from app.schemas.common import DomainRef, JobRef
from app.schemas.jobs import DomainJobAccepted
from app.schemas.media import AudioAccessResponse, RepeatRequest
from app.schemas.rooms import Message, MessageAccepted
from app.services.jobs import get_job_execution_policy


class MediaService(Protocol):
    def get_audio(self, authenticated_user_id: UUID, message_id: UUID) -> AudioAccessResponse: ...
    def retry_tts(
        self, authenticated_user_id: UUID, message_id: UUID, key: UUID
    ) -> DomainJobAccepted: ...
    def repeat(
        self, authenticated_user_id: UUID, message_id: UUID, request: RepeatRequest, key: UUID
    ) -> MessageAccepted: ...


class SqlMediaService:
    def __init__(
        self, repository: MediaRepository, signer: StorageSigner, user_queue_limit: int
    ) -> None:
        self._repository = repository
        self._signer = signer
        self._user_queue_limit = user_queue_limit

    def get_audio(self, authenticated_user_id: UUID, message_id: UUID) -> AudioAccessResponse:
        row = self._repository.get_audio(authenticated_user_id, message_id)
        if row is None:
            raise ApiError(404, "AUDIO_NOT_FOUND", "오디오를 찾을 수 없습니다.")
        if row["status"] != "ready":
            return AudioAccessResponse(
                status=row["status"], signed_url=None, expires_at=None, audio_type=row["audio_type"]
            )
        try:
            signed_url, expires_at = self._signer.create_signed_url(
                "message-audio", row["storage_path"], 300
            )
        except RuntimeError as error:
            raise ApiError(
                503, "STORAGE_UNAVAILABLE", "오디오 접근 URL을 만들 수 없습니다.", retryable=True
            ) from error
        return AudioAccessResponse(
            status="ready",
            signed_url=signed_url,
            expires_at=expires_at,
            audio_type=row["audio_type"],
        )

    def retry_tts(
        self, authenticated_user_id: UUID, message_id: UUID, key: UUID
    ) -> DomainJobAccepted:
        del key
        try:
            value = self._repository.retry_tts(
                authenticated_user_id,
                message_id,
                get_job_execution_policy("tts_generation").deadline_seconds,
            )
        except RuntimeError as error:
            raise ApiError(409, "AUDIO_NOT_RETRYABLE", str(error)) from error
        if value is None:
            raise ApiError(404, "AUDIO_NOT_FOUND", "오디오를 찾을 수 없습니다.")
        target_id, job = value
        return DomainJobAccepted(
            target=DomainRef(type="message_audio", id=target_id),
            job=JobRef(job_id=job["id"], type=job["type"], status=job["status"]),
        )

    def repeat(
        self, authenticated_user_id: UUID, message_id: UUID, request: RepeatRequest, key: UUID
    ) -> MessageAccepted:
        try:
            value = self._repository.create_repeat(
                authenticated_user_id,
                message_id,
                request.recommended_expression,
                key,
                get_job_execution_policy("conversation_text").deadline_seconds,
                self._user_queue_limit,
            )
        except (RuntimeError, OverflowError) as error:
            code = "USER_QUEUE_LIMIT" if "queue" in str(error) else "REPEAT_NOT_ALLOWED"
            status = 429 if code == "USER_QUEUE_LIMIT" else 409
            raise ApiError(status, code, str(error), retryable=status == 429) from error
        if value is None:
            raise ApiError(404, "RECOMMENDATION_NOT_FOUND", "허용된 추천 표현을 찾을 수 없습니다.")
        message, job = value
        return MessageAccepted(
            message=Message.model_validate(message),
            job=JobRef(job_id=job["id"], type=job["type"], status=job["status"]),
        )
