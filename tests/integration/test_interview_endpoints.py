from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.auth import TokenClaims
from app.main import create_app
from app.routers.interviews import get_interview_service
from tests.integration.test_auth_and_errors import ActiveSessionValidator, StubTokenVerifier


class StubInterviewService:
    def create_setup(self, user_id: Any, request: Any, key: Any) -> dict[str, Any]:
        return {
            "id": uuid4(),
            "desired_role": request.desired_role,
            "application_type": request.application_type,
            "status": "draft",
            "preparation_progress": 0,
        }

    def get_document(self, user_id: Any, document_id: Any) -> Any:
        raise NotImplementedError


def test_interview_setup_contract_is_registered() -> None:
    user_id = uuid4()
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
    app.dependency_overrides[get_interview_service] = lambda: StubInterviewService()
    client = TestClient(app)

    response = client.post(
        "/api/v1/interview-setups",
        headers={"Authorization": "Bearer good", "Idempotency-Key": str(uuid4())},
        json={"desired_role": "Backend Engineer", "application_type": "new_hire"},
    )

    assert response.status_code == 201
    assert response.json()["desired_role"] == "Backend Engineer"
    assert "user_id" not in response.json()

    operation = app.openapi()["paths"]["/api/v1/interview-setups"]["post"]
    assert operation["operationId"] == "interview_setup.create"
    assert any(
        parameter["name"] == "Idempotency-Key" and parameter["required"]
        for parameter in operation["parameters"]
    )


def test_interview_setup_requires_idempotency_key() -> None:
    user_id = uuid4()
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
    app.dependency_overrides[get_interview_service] = lambda: StubInterviewService()
    client = TestClient(app)

    response = client.post(
        "/api/v1/interview-setups",
        headers={"Authorization": "Bearer good"},
        json={"desired_role": "Backend Engineer"},
    )

    assert response.status_code == 422


def test_all_interview_contract_routes_are_exposed() -> None:
    paths = create_app().openapi()["paths"]
    expected = {
        "/api/v1/interview-documents",
        "/api/v1/interview-documents/{document_id}",
        "/api/v1/interview-documents/{document_id}/analyze",
        "/api/v1/interview-documents/{document_id}/replace",
        "/api/v1/interview-analyses/{analysis_id}",
        "/api/v1/interview-configurations",
        "/api/v1/interview-configurations/{configuration_id}",
        "/api/v1/interview-configurations/{configuration_id}/questions",
        "/api/v1/interview-configurations/{configuration_id}/regenerate",
        "/api/v1/interview-configurations/{configuration_id}/practice-room",
    }
    assert expected <= set(paths)
