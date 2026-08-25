from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.auth import TokenClaims
from app.main import create_app
from app.routers.feedback import get_feedback_service
from app.schemas.common import DomainRef, JobRef
from app.schemas.feedback import FeedbackResponse
from app.schemas.jobs import DomainJobAccepted
from app.services.feedback import FeedbackService
from tests.integration.test_auth_and_errors import StubTokenVerifier

USER_ID = uuid4()
MESSAGE_ID = uuid4()
TARGET_ID = uuid4()
JOB_ID = uuid4()


class StubFeedbackService(FeedbackService):
    def get_feedback(self, user_id: Any, message_id: Any) -> FeedbackResponse:
        return FeedbackResponse(
            status="partial",
            overall_score=None,
            summary="일부 분석 완료",
            scores=[],
            emotions=[],
            error=None,
        )

    def retry_feedback(
        self, user_id: Any, message_id: Any, idempotency_key: Any
    ) -> DomainJobAccepted:
        return accepted("turn_feedback")

    def retry_emotion(
        self, user_id: Any, message_id: Any, idempotency_key: Any
    ) -> DomainJobAccepted:
        return accepted("emotion_analysis")


def accepted(job_type: str) -> DomainJobAccepted:
    return DomainJobAccepted(
        target=DomainRef(type=job_type, id=TARGET_ID),
        job=JobRef(job_id=JOB_ID, type=job_type, status="queued"),
    )


def client() -> TestClient:
    verifier = StubTokenVerifier(
        TokenClaims(
            sub=str(USER_ID),
            issuer="https://project.supabase.co/auth/v1",
            audience="authenticated",
        )
    )
    application = create_app(token_verifier=verifier)
    application.dependency_overrides[get_feedback_service] = lambda: StubFeedbackService()
    return TestClient(application)


AUTH = {"Authorization": "Bearer token"}


def test_feedback_and_retry_routes_are_exposed() -> None:
    api = client()

    assert api.get(f"/api/v1/messages/{MESSAGE_ID}/feedback", headers=AUTH).status_code == 200
    for suffix in ("feedback/retry", "emotion/retry"):
        response = api.post(
            f"/api/v1/messages/{MESSAGE_ID}/{suffix}",
            headers={**AUTH, "Idempotency-Key": str(uuid4())},
            json={},
        )
        assert response.status_code == 202
        assert response.json()["target"]["id"] == str(TARGET_ID)
