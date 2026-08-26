from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Protocol
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.dependencies import get_session
from app.core.errors import ApiError


class TokenClaims(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub: str
    session_id: UUID | None = None
    issuer: str
    audience: str | list[str]
    user_metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID
    session_id: UUID
    access_token: str


class TokenVerifier(Protocol):
    def verify(self, token: str) -> TokenClaims: ...


class SessionValidator(Protocol):
    def validate(
        self,
        user_id: UUID,
        session_id: UUID,
        *,
        allow_account_deletion_in_progress: bool = False,
    ) -> bool: ...


class SessionValidationUnavailable(RuntimeError):
    pass


class SqlSessionValidator:
    def __init__(self, session: Session) -> None:
        self._session = session

    def validate(
        self,
        user_id: UUID,
        session_id: UUID,
        *,
        allow_account_deletion_in_progress: bool = False,
    ) -> bool:
        try:
            return bool(
                self._session.execute(
                    text(
                        """
                        select exists (
                            select 1
                            from auth.sessions s
                            where s.id = :session_id and s.user_id = :user_id
                        ) and (
                            :allow_deletion
                            or not exists (
                                select 1
                                from public.idempotency_records i
                                where i.user_id = :user_id
                                  and i.action_scope = 'account.delete'
                                  and i.state = 'in_progress'
                            )
                        )
                        """
                    ),
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "allow_deletion": allow_account_deletion_in_progress,
                    },
                ).scalar_one()
            )
        except SQLAlchemyError as error:
            self._session.rollback()
            raise SessionValidationUnavailable from error


class UnconfiguredSessionValidator:
    def validate(
        self,
        _user_id: UUID,
        _session_id: UUID,
        *,
        allow_account_deletion_in_progress: bool = False,
    ) -> bool:
        del allow_account_deletion_in_progress
        raise SessionValidationUnavailable


class JwksTokenVerifier:
    def __init__(self, jwks_url: str, issuer: str, audience: str, leeway_seconds: int = 0) -> None:
        self._jwks_client = PyJWKClient(jwks_url, lifespan=600)
        self._issuer = issuer
        self._audience = audience
        self._leeway_seconds = leeway_seconds

    def verify(self, token: str) -> TokenClaims:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[signing_key.algorithm_name],
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway_seconds,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            return TokenClaims(
                sub=payload["sub"],
                session_id=payload.get("session_id"),
                issuer=payload["iss"],
                audience=payload["aud"],
                user_metadata=payload.get("user_metadata", {}),
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
            raise ApiError(
                401,
                "INVALID_ACCESS_TOKEN",
                "인증 정보가 유효하지 않습니다.",
            ) from error


class UnconfiguredTokenVerifier:
    def verify(self, _token: str) -> TokenClaims:
        raise ApiError(
            503,
            "AUTH_SERVICE_NOT_CONFIGURED",
            "인증 서비스를 사용할 수 없습니다.",
            retryable=True,
        )


bearer_scheme = HTTPBearer(auto_error=False)


def get_token_verifier() -> TokenVerifier:
    return UnconfiguredTokenVerifier()


def get_session_validator(
    session: Annotated[Session, Depends(get_session)],
) -> SessionValidator:
    return SqlSessionValidator(session)


def get_authenticated_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    session_validator: Annotated[SessionValidator, Depends(get_session_validator)],
) -> AuthenticatedUser:
    return _authenticate(credentials, verifier, session_validator, allow_deletion=False)


def get_account_deletion_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    session_validator: Annotated[SessionValidator, Depends(get_session_validator)],
) -> AuthenticatedUser:
    return _authenticate(credentials, verifier, session_validator, allow_deletion=True)


def _authenticate(
    credentials: HTTPAuthorizationCredentials | None,
    verifier: TokenVerifier,
    session_validator: SessionValidator,
    *,
    allow_deletion: bool,
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(
            401,
            "AUTHENTICATION_REQUIRED",
            "인증이 필요합니다.",
        )

    claims = verifier.verify(credentials.credentials)
    try:
        authenticated_user_id = UUID(claims.sub)
    except ValueError as error:
        raise ApiError(
            401,
            "INVALID_ACCESS_TOKEN",
            "인증 정보가 유효하지 않습니다.",
        ) from error
    if claims.session_id is None:
        raise ApiError(401, "INVALID_AUTH_SESSION", "인증 세션이 유효하지 않습니다.")
    try:
        active = session_validator.validate(
            authenticated_user_id,
            claims.session_id,
            allow_account_deletion_in_progress=allow_deletion,
        )
    except SessionValidationUnavailable as error:
        raise ApiError(
            503,
            "AUTH_SESSION_UNAVAILABLE",
            "인증 세션을 확인할 수 없습니다.",
            retryable=True,
        ) from error
    if not active:
        raise ApiError(401, "INVALID_AUTH_SESSION", "인증 세션이 유효하지 않습니다.")
    return AuthenticatedUser(
        id=authenticated_user_id,
        session_id=claims.session_id,
        access_token=credentials.credentials,
    )
