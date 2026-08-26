from datetime import UTC, datetime
from inspect import getsource
from typing import Any
from uuid import uuid4

from app.schemas.rooms import RoomCreateRequest
from app.services.conversation import ROOM_CREATE_SCOPE, SqlConversationService
from app.services.idempotency import IdempotencyClaim
from app.services.interviews import SqlInterviewService


class RepositoryMustNotRun:
    def find_active_room(self, *_args: object) -> None:
        raise AssertionError("domain repository must not run during replay")


class ReplayIdempotency:
    def __init__(self, response_body: dict[str, Any]) -> None:
        self.response_body = response_body
        self.scope: str | None = None

    def claim(
        self, _user_id: object, scope: str, *_args: object, **_kwargs: object
    ) -> IdempotencyClaim:
        self.scope = scope
        return IdempotencyClaim(
            kind="replay", response_status=201, response_body=self.response_body
        )


def test_completed_room_request_replays_without_domain_write() -> None:
    now = datetime.now(UTC)
    room_id = uuid4()
    persona_id = uuid4()
    body = {
        "id": str(room_id),
        "title": "로컬 시연",
        "practice_type": "free_chat",
        "persona_id": str(persona_id),
        "scenario_id": None,
        "status": "in_progress",
        "turn_count": 0,
        "ended_reason": None,
        "started_at": now.isoformat(),
        "completed_at": None,
        "updated_at": now.isoformat(),
    }
    idempotency = ReplayIdempotency(body)
    service = SqlConversationService(
        RepositoryMustNotRun(),  # type: ignore[arg-type]
        20,
        4,
        idempotency,  # type: ignore[arg-type]
    )

    room, created = service.create_room(
        uuid4(),
        RoomCreateRequest(practice_type="free_chat", persona_id=persona_id, scenario_id=None),
        uuid4(),
    )

    assert room.id == room_id, "AC-T5-DEMO-IDEMPOTENCY"
    assert created is False
    assert idempotency.scope == ROOM_CREATE_SCOPE == "room.create", "AC-T5-DEMO-IDEMPOTENCY"


def test_all_agreed_demo_actions_are_wired_to_idempotency() -> None:
    source = (
        f'"{ROOM_CREATE_SCOPE}"'
        + getsource(SqlConversationService)
        + getsource(SqlInterviewService)
    )

    for scope in {
        "room.create",
        "room_message.create",
        "interview_document.create",
        "interview_document.analyze",
        "interview_configuration.generate",
        "interview_practice_room.create",
    }:
        assert f'"{scope}"' in source, "AC-T5-DEMO-IDEMPOTENCY"
