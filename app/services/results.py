from typing import Protocol
from uuid import UUID

from app.core.errors import ApiError
from app.repositories.results import ResultRepository
from app.schemas.common import DomainRef, JobRef
from app.schemas.jobs import DomainJobAccepted
from app.schemas.pagination import Page
from app.schemas.results import SessionResult, SessionResultSummary
from app.services.jobs import get_job_execution_policy


class ResultService(Protocol):
    def get_room_result(self, authenticated_user_id: UUID, room_id: UUID) -> SessionResult: ...
    def retry_room_result(
        self, authenticated_user_id: UUID, room_id: UUID, key: UUID
    ) -> DomainJobAccepted: ...
    def list_results(
        self, authenticated_user_id: UUID, cursor: str | None, limit: int | None
    ) -> Page[SessionResultSummary]: ...
    def get_result(self, authenticated_user_id: UUID, result_id: UUID) -> SessionResult: ...
    def delete_result(self, authenticated_user_id: UUID, result_id: UUID, key: UUID) -> None: ...


class SqlResultService:
    def __init__(self, repository: ResultRepository, pagination_limit: int) -> None:
        self._repository = repository
        self._pagination_limit = pagination_limit

    def get_room_result(self, authenticated_user_id: UUID, room_id: UUID) -> SessionResult:
        row = self._repository.get_by_room(authenticated_user_id, room_id)
        if row is None:
            raise ApiError(404, "RESULT_NOT_FOUND", "결과를 찾을 수 없습니다.")
        if row["status"] == "processing":
            raise ApiError(409, "RESULT_PROCESSING", "결과를 생성하고 있습니다.", retryable=True)
        return SessionResult.model_validate(row)

    def retry_room_result(
        self, authenticated_user_id: UUID, room_id: UUID, key: UUID
    ) -> DomainJobAccepted:
        del key
        try:
            value = self._repository.retry(
                authenticated_user_id,
                room_id,
                get_job_execution_policy("session_result_generation").deadline_seconds,
            )
        except RuntimeError as error:
            raise ApiError(409, "RESULT_NOT_RETRYABLE", str(error)) from error
        if value is None:
            raise ApiError(404, "RESULT_NOT_FOUND", "결과를 찾을 수 없습니다.")
        target_id, job = value
        return DomainJobAccepted(
            target=DomainRef(type="session_result", id=target_id),
            job=JobRef(job_id=job["id"], type=job["type"], status=job["status"]),
        )

    def list_results(
        self, authenticated_user_id: UUID, cursor: str | None, limit: int | None
    ) -> Page[SessionResultSummary]:
        if cursor is not None:
            raise ApiError(422, "INVALID_CURSOR", "현재 cursor를 해석할 수 없습니다.")
        size = min(limit or self._pagination_limit, self._pagination_limit)
        return Page(
            items=[
                SessionResultSummary.model_validate(row)
                for row in self._repository.list(authenticated_user_id, size)
            ],
            next_cursor=None,
        )

    def get_result(self, authenticated_user_id: UUID, result_id: UUID) -> SessionResult:
        row = self._repository.get(authenticated_user_id, result_id)
        if row is None:
            raise ApiError(404, "RESULT_NOT_FOUND", "결과를 찾을 수 없습니다.")
        return SessionResult.model_validate(row)

    def delete_result(self, authenticated_user_id: UUID, result_id: UUID, key: UUID) -> None:
        del key
        try:
            deleted = self._repository.delete(authenticated_user_id, result_id)
        except RuntimeError as error:
            raise ApiError(409, "RESULT_JOB_ACTIVE", str(error), retryable=True) from error
        if not deleted:
            raise ApiError(404, "RESULT_NOT_FOUND", "결과를 찾을 수 없습니다.")
