from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Protocol
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ApiError


class TokenClaims(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub: str
    issuer: str
    audience: str | list[str]
    user_metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID


class TokenVerifier(Protocol):
    def verify(self, token: str) -> TokenClaims: ...


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


def get_authenticated_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
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
    return AuthenticatedUser(id=authenticated_user_id)
