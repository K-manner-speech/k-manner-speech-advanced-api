from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.errors import ApiError
from app.repositories.catalog import CatalogRepository
from app.repositories.conversation import ConversationRepository
from app.schemas.rooms import MessageCreateRequest, RoomCreateRequest
from app.services.catalog import SqlCatalogService
from app.services.conversation import SqlConversationService


class EmptyMappings:
    def mappings(self) -> EmptyMappings:
        return self

    def __iter__(self) -> Any:
        return iter(())


class SqlCapturingSession:
    def __init__(self) -> None:
        self.statement = ""

    def execute(self, statement: Any, _parameters: Any = None) -> EmptyMappings:
        self.statement = str(statement)
        return EmptyMappings()


def test_scenario_list_casts_nullable_persona_uuid() -> None:
    session = SqlCapturingSession()
    repository = CatalogRepository(session)  # type: ignore[arg-type]

    assert repository.list_scenarios(10, None) == []
    assert "cast(:persona_id as uuid) is null" in session.statement, "AC-T1-CATALOG-NULL-UUID"


class CatalogRepositoryStub:
    def persona_exists(self, _persona_id: UUID) -> bool:
        return False

    def list_scenarios(self, _limit: int, _persona_id: UUID | None) -> list[dict[str, Any]]:
        raise AssertionError("scenario query must not run for an unknown persona")


def test_scenario_list_rejects_unknown_persona() -> None:
    service = SqlCatalogService(CatalogRepositoryStub(), maximum_limit=20)  # type: ignore[arg-type]

    with pytest.raises(ApiError) as raised:
        service.list_scenarios(None, 10, uuid4())

    error = raised.value
    assert getattr(error, "status_code", None) == 404
    assert getattr(error, "code", None) == "PERSONA_NOT_FOUND"


class InvalidRoomRepository:
    def __init__(self) -> None:
        self.committed = False

    def find_active_room(self, _user_id: UUID, _request: RoomCreateRequest) -> None:
        return None

    def validate_catalog(self, _request: RoomCreateRequest) -> dict[str, Any]:
        return {"persona_name": "테스트", "scenario_title": "시나리오", "goal": "목표"}

    def create_room(
        self,
        _user_id: UUID,
        request: RoomCreateRequest,
        _catalog: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "id": uuid4(),
            "title": "시나리오",
            "practice_type": request.practice_type,
            "persona_id": request.persona_id,
            "scenario_id": request.scenario_id,
            "status": "in_progress",
            "turn_count": 0,
            "ended_reason": None,
            "started_at": now,
            "completed_at": None,
            "updated_at": now,
            "goal": "Room 계약에 없는 필드",
        }

    def commit(self) -> None:
        self.committed = True


def test_room_is_validated_before_commit() -> None:
    repository = InvalidRoomRepository()
    service = SqlConversationService(repository, 20, 4)  # type: ignore[arg-type]
    request = RoomCreateRequest(
        practice_type="scenario",
        persona_id=uuid4(),
        scenario_id=uuid4(),
    )

    try:
        service.create_room(uuid4(), request, uuid4())
    except ValidationError:
        pass
    else:
        pytest.fail("AC-T2-ROOM-CREATE-ATOMIC")

    assert repository.committed is False, "AC-T2-ROOM-CREATE-ATOMIC"


def test_room_list_casts_nullable_text_filters() -> None:
    session = SqlCapturingSession()
    repository = ConversationRepository(session)  # type: ignore[arg-type]

    assert repository.list_rooms(uuid4(), 20, "in_progress", "free_chat") == []
    assert "cast(:status as text) is null" in session.statement
    assert "status = cast(:status as text)" in session.statement
    assert "cast(:practice_type as text) is null" in session.statement
    assert "practice_type = cast(:practice_type as text)" in session.statement


class MessageRepositoryMustNotRun:
    def create_message_and_job(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("repository must not run for mismatched request identifiers")


def test_message_rejects_mismatched_client_request_id_as_api_error() -> None:
    service = SqlConversationService(MessageRepositoryMustNotRun(), 20, 4)  # type: ignore[arg-type]
    request = MessageCreateRequest(
        content="안녕하세요",
        input_mode="text",
        client_request_id=uuid4(),
    )

    with pytest.raises(Exception) as raised:
        service.create_message(uuid4(), uuid4(), request, uuid4())

    error = raised.value
    assert getattr(error, "status_code", None) == 422
    assert getattr(error, "code", None) == "CLIENT_REQUEST_ID_MISMATCH"
