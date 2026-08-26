from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.auth import TokenClaims
from app.main import create_app
from app.routers.users import get_account_deletion_service
from tests.integration.test_auth_and_errors import (
    ActiveSessionValidator,
    StubTokenVerifier,
)


class StubAccountDeletionService:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def delete_account(self, user_id: Any, access_token: str, key: Any) -> None:
        self.calls.append((user_id, access_token, key))


def test_account_delete_endpoint_returns_204_and_passes_sensitive_credentials() -> None:
    user_id = uuid4()
    session_id = uuid4()
    service = StubAccountDeletionService()
    session_validator = ActiveSessionValidator()
    app = create_app(
        token_verifier=StubTokenVerifier(
            TokenClaims(
                sub=str(user_id),
                session_id=session_id,
                issuer="https://project.supabase.co/auth/v1",
                audience="authenticated",
            )
        ),
        session_validator=session_validator,
    )
    app.dependency_overrides[get_account_deletion_service] = lambda: service
    client = TestClient(app)
    key = uuid4()

    response = client.delete(
        "/api/v1/me",
        headers={
            "Authorization": "Bearer access-token",
            "Idempotency-Key": str(key),
        },
    )

    assert response.status_code == 204
    assert response.content == b""
    assert service.calls == [(user_id, "access-token", key)]
    assert session_validator.calls == [(user_id, session_id, True)]


def test_account_delete_requires_idempotency_key() -> None:
    user_id = uuid4()
    service = StubAccountDeletionService()
    app = create_app(
        token_verifier=StubTokenVerifier(
            TokenClaims(
                sub=str(user_id),
                session_id=uuid4(),
                issuer="https://project.supabase.co/auth/v1",
                audience="authenticated",
            )
        ),
        session_validator=ActiveSessionValidator(),
    )
    app.dependency_overrides[get_account_deletion_service] = lambda: service

    response = TestClient(app).delete(
        "/api/v1/me", headers={"Authorization": "Bearer access-token"}
    )

    assert response.status_code == 422
    assert service.calls == []
