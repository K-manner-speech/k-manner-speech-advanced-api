from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.account_auth import (
    AccountAuthGateway,
    AuthGatewayUnavailable,
    AuthReconfirmationError,
)
from app.adapters.storage import StorageObjectStore
from app.core.errors import ApiError
from app.repositories.account import AccountDeletionRepository
from app.services.idempotency import IdempotencyRepository, request_fingerprint


class AccountDeletionService(Protocol):
    def delete_account(self, user_id: UUID, access_token: str, key: UUID) -> None: ...


class SqlAccountDeletionService:
    def __init__(
        self,
        repository: AccountDeletionRepository,
        storage: StorageObjectStore,
        auth_gateway: AccountAuthGateway,
        idempotency: IdempotencyRepository,
        idempotency_lease_seconds: int,
        idempotency_retention_seconds: int,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._auth_gateway = auth_gateway
        self._idempotency = idempotency
        self._idempotency_lease_seconds = idempotency_lease_seconds
        self._idempotency_retention_seconds = idempotency_retention_seconds

    def delete_account(self, user_id: UUID, access_token: str, key: UUID) -> None:
        self._reconfirm_user(access_token, user_id)
        action_scope = "account.delete"
        try:
            claim = self._idempotency.claim(
                user_id,
                action_scope,
                key,
                request_fingerprint({}),
                self._idempotency_lease_seconds,
            )
            if claim.kind == "replay":
                self._repository.rollback()
                return
            if claim.claim_token is None:
                raise RuntimeError("idempotency claim token is missing")
            self._repository.commit()
        except ApiError:
            self._repository.rollback()
            raise
        except (RuntimeError, SQLAlchemyError) as error:
            self._repository.rollback()
            raise ApiError(
                503,
                "ACCOUNT_DELETION_UNAVAILABLE",
                "회원 탈퇴를 시작할 수 없습니다.",
                retryable=True,
            ) from error

        try:
            objects = self._repository.list_storage_objects(user_id)
            self._repository.cancel_jobs_and_cleanup_queues(user_id)
            self._repository.commit()
            for stored_object in objects:
                self._storage.delete(
                    stored_object.bucket_id, stored_object.storage_path
                )
            remaining = self._repository.list_storage_objects(user_id)
            self._repository.commit()
            if remaining:
                raise RuntimeError("storage objects remain")
            self._auth_gateway.delete_user(user_id)
        except (RuntimeError, SQLAlchemyError, AuthGatewayUnavailable) as error:
            self._record_retryable_failure(
                user_id, key, claim.claim_token, "ACCOUNT_DELETION_INCOMPLETE"
            )
            raise ApiError(
                503,
                "ACCOUNT_DELETION_INCOMPLETE",
                "회원 탈퇴를 완료하지 못했습니다.",
                retryable=True,
            ) from error

    def _reconfirm_user(self, access_token: str, user_id: UUID) -> None:
        try:
            self._auth_gateway.reconfirm_user(access_token, user_id)
        except AuthReconfirmationError as error:
            raise ApiError(
                401,
                "ACCOUNT_RECONFIRMATION_FAILED",
                "회원 정보를 다시 확인할 수 없습니다.",
            ) from error
        except AuthGatewayUnavailable as error:
            raise ApiError(
                503,
                "AUTH_SERVICE_UNAVAILABLE",
                "인증 서비스를 사용할 수 없습니다.",
                retryable=True,
            ) from error

    def _record_retryable_failure(
        self,
        user_id: UUID,
        key: UUID,
        claim_token: UUID,
        error_code: str,
    ) -> None:
        self._repository.rollback()
        try:
            self._idempotency.fail_retryable(
                user_id,
                "account.delete",
                key,
                claim_token,
                error_code,
                self._idempotency_retention_seconds,
            )
            self._repository.commit()
        except (RuntimeError, SQLAlchemyError):
            self._repository.rollback()
