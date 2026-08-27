from typing import Protocol
from uuid import UUID

from app.core.errors import ApiError
from app.repositories.feedback import FeedbackRepository
from app.schemas.common import DomainRef, JobRef
from app.schemas.feedback import FeedbackResponse, FeedbackSafeError
from app.schemas.jobs import DomainJobAccepted
from app.services.jobs import get_job_execution_policy


class FeedbackService(Protocol):
    def get_feedback(self, user_id: UUID, message_id: UUID) -> FeedbackResponse: ...
    def retry_feedback(
        self, user_id: UUID, message_id: UUID, idempotency_key: UUID
    ) -> DomainJobAccepted: ...
    def retry_emotion(
        self, user_id: UUID, message_id: UUID, idempotency_key: UUID
    ) -> DomainJobAccepted: ...


class SqlFeedbackService:
    def __init__(self, repository: FeedbackRepository) -> None:
        self._repository = repository

    def get_feedback(self, user_id: UUID, message_id: UUID) -> FeedbackResponse:
        row = self._repository.get_feedback(user_id, message_id)
        if row is None:
            raise ApiError(404, "FEEDBACK_NOT_FOUND", "피드백을 찾을 수 없습니다.")
        error = None
        if row["error_code"]:
            error = FeedbackSafeError(code=row["error_code"], retryable=True)
        scores = [
            {
                **score,
                "score": int(score["score"]),
                "max_score": int(score["max_score"]),
            }
            for score in row["scores"]
        ]
        return FeedbackResponse(
            status=row["status"],
            overall_score=(
                int(row["overall_score"]) if row["overall_score"] is not None else None
            ),
            summary=row["summary"],
            scores=scores,
            emotions=row["emotions"],
            error=error,
        )

    def retry_feedback(
        self, user_id: UUID, message_id: UUID, idempotency_key: UUID
    ) -> DomainJobAccepted:
        del idempotency_key
        return self._retry(user_id, message_id, "turn_feedback")

    def retry_emotion(
        self, user_id: UUID, message_id: UUID, idempotency_key: UUID
    ) -> DomainJobAccepted:
        del idempotency_key
        return self._retry(user_id, message_id, "emotion_analysis")

    def _retry(self, user_id: UUID, message_id: UUID, job_type: str) -> DomainJobAccepted:
        policy = get_job_execution_policy(job_type)
        try:
            if job_type == "emotion_analysis":
                retried = self._repository.retry_emotion(
                    user_id, message_id, policy.deadline_seconds
                )
            else:
                retried = self._repository.retry_feedback(
                    user_id, message_id, policy.deadline_seconds
                )
            if retried is None:
                raise ApiError(404, "MESSAGE_ANALYSIS_NOT_FOUND", "분석 대상을 찾을 수 없습니다.")
            target_id, job = retried
            self._repository.commit()
        except RuntimeError as error:
            raise ApiError(
                409, "ANALYSIS_NOT_RETRYABLE", "현재 분석은 재시도할 수 없습니다."
            ) from error
        return DomainJobAccepted(
            target=DomainRef(type=job_type, id=target_id),
            job=JobRef(job_id=job["id"], type=job["type"], status=job["status"]),
        )
