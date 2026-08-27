from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.auth import TokenClaims
from app.main import create_app
from app.routers.media import get_media_service
from app.routers.results import get_result_service
from app.schemas.jobs import DomainJobAccepted
from app.schemas.media import AudioAccessResponse
from app.schemas.results import SessionResult
from tests.integration.test_auth_and_errors import ActiveSessionValidator, StubTokenVerifier


class StubMediaService:
    def get_audio(self, authenticated_user_id: Any, message_id: Any) -> AudioAccessResponse:
        return AudioAccessResponse(
            status="ready",
            signed_url="https://storage.example/signed",
            expires_at=datetime.now(UTC),
            audio_type="persona_tts",
        )

    def retry_tts(self, authenticated_user_id: Any, message_id: Any, key: Any) -> Any:
        return DomainJobAccepted.model_validate(
            {
                "target": {"type": "message_audio", "id": uuid4()},
                "job": {"job_id": uuid4(), "type": "tts_generation", "status": "queued"},
            }
        )

    def repeat(self, authenticated_user_id: Any, message_id: Any, request: Any, key: Any) -> Any:
        raise NotImplementedError


class StubResultService:
    def get_room_result(self, authenticated_user_id: Any, room_id: Any) -> SessionResult:
        return SessionResult(
            id=uuid4(),
            attempt_no=1,
            status="succeeded",
            missing_categories=[],
            created_at=datetime.now(UTC),
            items=[],
            source_refs=[],
        )

    def retry_room_result(self, authenticated_user_id: Any, room_id: Any, key: Any) -> Any:
        raise NotImplementedError

    def list_results(self, authenticated_user_id: Any, cursor: Any, limit: Any) -> Any:
        raise NotImplementedError

    def get_result(self, authenticated_user_id: Any, result_id: Any) -> Any:
        raise NotImplementedError

    def delete_result(self, authenticated_user_id: Any, result_id: Any, key: Any) -> None:
        raise NotImplementedError


def test_audio_and_result_routes_use_safe_response_models() -> None:
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
    app.dependency_overrides[get_media_service] = lambda: StubMediaService()
    app.dependency_overrides[get_result_service] = lambda: StubResultService()
    client = TestClient(app)

    audio = client.get(
        f"/api/v1/messages/{uuid4()}/audio", headers={"Authorization": "Bearer good"}
    )
    result = client.get(f"/api/v1/rooms/{uuid4()}/result", headers={"Authorization": "Bearer good"})

    assert audio.status_code == 200
    assert "storage_path" not in audio.json()
    assert result.status_code == 200
    assert "source_snapshot" not in result.json()
