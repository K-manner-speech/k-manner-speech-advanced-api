from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.core.auth import (
    AuthenticatedUser,
    JwksTokenVerifier,
    TokenClaims,
    TokenVerifier,
    get_authenticated_user,
    get_token_verifier,
)
from app.core.config import AppSettings
from app.core.errors import ApiError
from app.main import create_app
from tests.unit.test_core_config import complete_settings


class StubTokenVerifier(TokenVerifier):
    def __init__(self, claims: TokenClaims | None = None) -> None:
        self.claims = claims
        self.received_token: str | None = None

    def verify(self, token: str) -> TokenClaims:
        self.received_token = token
        if self.claims is None:
            raise ApiError(401, "INVALID_ACCESS_TOKEN", "인증 정보가 유효하지 않습니다.")
        return self.claims


def protected_client(verifier: TokenVerifier) -> TestClient:
    router = APIRouter()

    @router.get("/protected")
    def protected(
        user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    ) -> dict[str, str]:
        return {"user_id": str(user.id)}

    app = create_app(token_verifier=verifier)
    app.include_router(router)
    return TestClient(app)


def test_missing_bearer_returns_safe_401_envelope() -> None:
    client = protected_client(StubTokenVerifier())

    response = client.get("/protected")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert response.json()["retryable"] is False
    UUID(response.json()["request_id"])
    assert "authorization" not in response.text.lower()


def test_verified_uuid_subject_is_the_only_authenticated_identity() -> None:
    user_id = uuid4()
    verifier = StubTokenVerifier(
        TokenClaims(
            sub=str(user_id),
            issuer="https://project.supabase.co/auth/v1",
            audience="authenticated",
            user_metadata={"user_id": str(uuid4()), "role": "admin"},
        )
    )
    client = protected_client(verifier)

    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer signed-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": str(user_id)}
    assert verifier.received_token == "signed-token"


def test_non_uuid_subject_is_rejected() -> None:
    verifier = StubTokenVerifier(
        TokenClaims(
            sub="not-a-uuid",
            issuer="https://project.supabase.co/auth/v1",
            audience="authenticated",
            user_metadata={},
        )
    )
    client = protected_client(verifier)

    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer signed-token"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_ACCESS_TOKEN"


def test_configured_app_installs_supabase_jwks_verifier() -> None:
    settings = AppSettings(_env_file=None, **complete_settings())
    app = create_app(settings=settings)

    verifier = app.dependency_overrides[get_token_verifier]()

    assert isinstance(verifier, JwksTokenVerifier)


def test_framework_validation_error_uses_common_envelope() -> None:
    router = APIRouter()

    @router.get("/validated")
    def validated(limit: int) -> dict[str, int]:
        return {"limit": limit}

    app = create_app()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/validated", params={"limit": "not-an-integer"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["field_errors"]
    UUID(response.json()["request_id"])
