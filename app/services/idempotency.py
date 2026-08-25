from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import ApiError


def request_fingerprint(payload: Any) -> bytes:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(canonical).digest()


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    kind: Literal["claimed", "replay"]
    claim_token: UUID | None = None
    response_status: int | None = None
    response_body: dict[str, Any] | None = None


class IdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def claim(
        self,
        user_id: UUID,
        action_scope: str,
        key: UUID,
        fingerprint: bytes,
        lease_seconds: int,
        retention_seconds: int,
    ) -> IdempotencyClaim:
        claim_token = uuid4()
        now = datetime.now(UTC)
        inserted = self._session.execute(
            text("""
                insert into public.idempotency_records
                    (user_id, action_scope, idempotency_key, request_fingerprint,
                     claim_token, lease_expires_at, expires_at)
                values
                    (:user_id, :scope, :key, :fingerprint,
                     :claim_token, :lease_expires_at, :expires_at)
                on conflict (user_id, action_scope, idempotency_key) do nothing
                returning id
            """),
            {
                "user_id": user_id,
                "scope": action_scope,
                "key": key,
                "fingerprint": fingerprint,
                "claim_token": claim_token,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "expires_at": now + timedelta(seconds=retention_seconds),
            },
        ).first()
        if inserted is not None:
            return IdempotencyClaim(kind="claimed", claim_token=claim_token)

        existing = (
            self._session.execute(
                text("""
                select request_fingerprint, state, claim_token, lease_expires_at,
                       response_status, response_body, error_retryable
                from public.idempotency_records
                where user_id = :user_id and action_scope = :scope
                  and idempotency_key = :key
                for update
            """),
                {"user_id": user_id, "scope": action_scope, "key": key},
            )
            .mappings()
            .one()
        )
        if bytes(existing["request_fingerprint"]) != fingerprint:
            raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "다른 요청에 사용된 멱등성 키입니다.")
        if existing["state"] == "completed":
            return IdempotencyClaim(
                kind="replay",
                response_status=existing["response_status"],
                response_body=existing["response_body"],
            )
        lease_active = existing["lease_expires_at"] and existing["lease_expires_at"] > now
        retryable_failed = existing["state"] == "failed" and existing["error_retryable"]
        if lease_active and not retryable_failed:
            raise ApiError(
                409,
                "IDEMPOTENCY_IN_PROGRESS",
                "같은 요청을 처리하고 있습니다.",
                retryable=True,
            )
        updated = self._session.execute(
            text("""
                update public.idempotency_records
                set state = 'in_progress', claim_token = :claim_token,
                    lease_expires_at = :lease_expires_at, error_code = null,
                    error_retryable = null, error_meta = null, updated_at = now()
                where user_id = :user_id and action_scope = :scope
                  and idempotency_key = :key
                  and (lease_expires_at <= :now or state = 'failed')
                returning id
            """),
            {
                "claim_token": claim_token,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "user_id": user_id,
                "scope": action_scope,
                "key": key,
                "now": now,
            },
        ).first()
        if updated is None:
            raise ApiError(
                409,
                "IDEMPOTENCY_IN_PROGRESS",
                "같은 요청을 처리하고 있습니다.",
                retryable=True,
            )
        return IdempotencyClaim(kind="claimed", claim_token=claim_token)

    def complete(
        self,
        user_id: UUID,
        action_scope: str,
        key: UUID,
        claim_token: UUID,
        response_status: int,
        response_body: dict[str, Any] | None,
        response_schema_version: str,
    ) -> None:
        updated = self._session.execute(
            text("""
                update public.idempotency_records
                set state = 'completed', response_status = :response_status,
                    response_body = cast(:response_body as jsonb),
                    response_schema_version = :schema_version,
                    completed_at = now(), lease_expires_at = null, updated_at = now()
                where user_id = :user_id and action_scope = :scope
                  and idempotency_key = :key and claim_token = :claim_token
                  and state = 'in_progress'
                returning id
            """),
            {
                "user_id": user_id,
                "scope": action_scope,
                "key": key,
                "claim_token": claim_token,
                "response_status": response_status,
                "response_body": json.dumps(response_body) if response_body is not None else None,
                "schema_version": response_schema_version,
            },
        ).first()
        if updated is None:
            raise RuntimeError("idempotency claim was lost")


def validate_client_request_id(
    client_request_id: UUID,
    idempotency_key: UUID,
) -> None:
    """Enforce the message contract's single retry identifier."""

    if client_request_id != idempotency_key:
        raise ValueError("client_request_id must match Idempotency-Key")
