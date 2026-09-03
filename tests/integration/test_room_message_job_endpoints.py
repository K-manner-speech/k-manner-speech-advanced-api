from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.auth import TokenClaims
from app.main import create_app
from app.routers.conversation import get_conversation_service
from app.schemas.common import Job, JobProgress, JobRef
from app.schemas.pagination import Page
from app.schemas.rooms import Message, MessageAccepted, Room, RoomDetail, RoomSummary
from app.services.conversation import ConversationService
from tests.integration.test_auth_and_errors import ActiveSessionValidator, StubTokenVerifier

USER_ID = uuid4()
ROOM_ID = uuid4()
MESSAGE_ID = uuid4()
JOB_ID = uuid4()
CONFIGURATION_ID = uuid4()
NOW = datetime.now(UTC)


def room() -> Room:
    return Room(
        id=ROOM_ID,
        title="업무 요청",
        practice_type="scenario",
        persona_id=uuid4(),
        scenario_id=uuid4(),
        status="in_progress",
        turn_count=0,
        ended_reason=None,
        started_at=NOW,
        completed_at=None,
        updated_at=NOW,
    )


def message() -> Message:
    return Message(
        id=MESSAGE_ID,
        room_id=ROOM_ID,
        sequence_no=1,
        sender_type="user",
        content="도움을 요청드립니다.",
        input_mode="text",
        delivery_status="sent",
        reply_to_message_id=None,
        emotion=None,
        created_at=NOW,
        updated_at=NOW,
    )


def job_ref() -> JobRef:
    return JobRef(job_id=JOB_ID, type="conversation_text", status="queued")


class StubConversationService(ConversationService):
    def create_room(self, user_id: Any, request: Any, idempotency_key: Any) -> tuple[Room, bool]:
        assert user_id == USER_ID
        return room(), True

    def list_rooms(
        self, user_id: Any, cursor: Any, limit: int, status: Any, practice_type: Any
    ) -> Any:
        return Page(items=[RoomSummary.model_validate(room().model_dump())], next_cursor=None)

    def get_room(self, user_id: Any, room_id: Any) -> RoomDetail:
        return RoomDetail(
            **room().model_dump(),
            goal="정중하게 요청하기",
            persona_name="민준 팀장",
            interview_configuration_id=CONFIGURATION_ID,
            current_interview_question_id=MESSAGE_ID,
        )

    def delete_room(self, user_id: Any, room_id: Any, idempotency_key: Any) -> None:
        return None

    def complete_interview(self, user_id: Any, room_id: Any) -> Room:
        return Room(
            **{
                **room().model_dump(),
                "practice_type": "interview",
                "status": "completed",
                "ended_reason": "completed",
                "completed_at": NOW,
            }
        )

    def complete_scenario(self, user_id: Any, room_id: Any) -> Room:
        return Room(
            **{
                **room().model_dump(),
                "practice_type": "scenario",
                "status": "completed",
                "ended_reason": "completed",
                "completed_at": NOW,
            }
        )

    def continue_after_goal(self, user_id: Any, room_id: Any) -> Room:
        return Room(
            **{
                **room().model_dump(),
                "practice_type": "scenario",
                "status": "in_progress",
                "ended_reason": None,
            }
        )

    def list_messages(self, user_id: Any, room_id: Any, cursor: Any, limit: int) -> Any:
        return Page(items=[message()], next_cursor=None)

    def create_message(self, user_id: Any, room_id: Any, request: Any, idempotency_key: Any) -> Any:
        return MessageAccepted(message=message(), job=job_ref())

    def retry_response(self, user_id: Any, message_id: Any, idempotency_key: Any) -> Any:
        return MessageAccepted(message=message(), job=job_ref())

    def get_job(self, user_id: Any, job_id: Any) -> Job:
        return Job(
            id=JOB_ID,
            type="conversation_text",
            status="queued",
            progress=JobProgress(stage=None, completed_units=None, total_units=None),
            error=None,
            result_resource=None,
            created_at=NOW,
            updated_at=NOW,
        )


def client() -> TestClient:
    verifier = StubTokenVerifier(
        TokenClaims(
            sub=str(USER_ID),
            session_id=uuid4(),
            issuer="https://project.supabase.co/auth/v1",
            audience="authenticated",
        )
    )
    application = create_app(
        token_verifier=verifier, session_validator=ActiveSessionValidator()
    )
    application.dependency_overrides[get_conversation_service] = lambda: StubConversationService()
    return TestClient(application)


AUTH = {"Authorization": "Bearer token"}


def test_room_routes_are_exposed() -> None:
    api = client()
    idem = str(uuid4())

    created = api.post(
        "/api/v1/rooms",
        headers={**AUTH, "Idempotency-Key": idem},
        json={
            "practice_type": "scenario",
            "persona_id": str(uuid4()),
            "scenario_id": str(uuid4()),
        },
    )
    assert created.status_code == 201
    assert api.get("/api/v1/rooms?limit=10", headers=AUTH).status_code == 200
    room_detail = api.get(f"/api/v1/rooms/{ROOM_ID}", headers=AUTH)
    assert room_detail.status_code == 200
    assert room_detail.json()["persona_name"] == "민준 팀장"
    assert room_detail.json()["interview_configuration_id"] == str(CONFIGURATION_ID)
    assert room_detail.json()["current_interview_question_id"] == str(MESSAGE_ID)
    assert (
        api.delete(
            f"/api/v1/rooms/{ROOM_ID}",
            headers={**AUTH, "Idempotency-Key": str(uuid4())},
        ).status_code
        == 204
    )
    completed = api.post(f"/api/v1/rooms/{ROOM_ID}/interview-complete", headers=AUTH)
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_scenario_goal_choice_routes_are_exposed() -> None:
    api = client()

    completed = api.post(f"/api/v1/rooms/{ROOM_ID}/complete", headers=AUTH)
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["ended_reason"] == "completed"

    # "계속하기"는 방을 끝내지 않고 조기 종료 안내만 걷어낸다.
    resumed = api.post(f"/api/v1/rooms/{ROOM_ID}/continue", headers=AUTH)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "in_progress"
    assert resumed.json()["ended_reason"] is None


def test_message_and_job_routes_are_exposed() -> None:
    api = client()
    idem = uuid4()

    accepted = api.post(
        f"/api/v1/rooms/{ROOM_ID}/messages",
        headers={**AUTH, "Idempotency-Key": str(idem)},
        json={
            "content": "도움을 요청드립니다.",
            "input_mode": "text",
            "client_request_id": str(idem),
        },
    )
    assert accepted.status_code == 202
    assert accepted.json()["job"]["job_id"] == str(JOB_ID)
    assert api.get(f"/api/v1/rooms/{ROOM_ID}/messages?limit=10", headers=AUTH).status_code == 200
    assert (
        api.post(
            f"/api/v1/messages/{MESSAGE_ID}/retry-response",
            headers={**AUTH, "Idempotency-Key": str(uuid4())},
            json={},
        ).status_code
        == 202
    )
    assert api.get(f"/api/v1/jobs/{JOB_ID}", headers=AUTH).status_code == 200
