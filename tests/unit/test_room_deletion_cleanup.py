from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.core.errors import ApiError
from app.services.conversation import SqlConversationService
from app.services.idempotency import IdempotencyClaim


def _service(storage: object | None, paths: list[str]) -> tuple[SqlConversationService, MagicMock]:
    repository = MagicMock()
    repository.get_room.return_value = {"id": uuid4()}
    repository.list_room_storage_paths.return_value = paths
    repository.delete_room.return_value = True
    service = SqlConversationService(repository, 20, 5, storage=storage)  # type: ignore[arg-type]
    return service, repository


def test_room_deletion_removes_the_rooms_audio_files() -> None:
    storage = MagicMock()
    user_id, room_id = uuid4(), uuid4()
    paths = [f"{user_id}/{room_id}/a.wav", f"{user_id}/{room_id}/b.webm"]
    service, repository = _service(storage, paths)

    service.delete_room(user_id, room_id, uuid4())

    assert storage.delete.call_count == 2
    assert storage.delete.call_args_list[0].args == ("message-audio", f"{user_id}/{room_id}/a.wav")
    assert storage.delete.call_args_list[1].args == ("message-audio", f"{user_id}/{room_id}/b.webm")
    assert repository.commit.call_count == 2


def test_storage_paths_are_read_before_the_room_row_disappears() -> None:
    storage = MagicMock()
    calls: list[str] = []
    service, repository = _service(storage, ["user/room/audio.wav"])
    repository.list_room_storage_paths.side_effect = (
        lambda *_: calls.append("list") or ["user/room/audio.wav"]
    )
    storage.delete.side_effect = lambda *_: calls.append("storage")
    repository.delete_room.side_effect = lambda *_: calls.append("delete") or True

    service.delete_room(uuid4(), uuid4(), uuid4())

    # 방을 지우면 message_audio가 함께 사라져 경로를 더 이상 찾을 수 없다.
    assert calls == ["list", "storage", "delete"]


def test_room_deletion_works_without_a_storage_client() -> None:
    service, repository = _service(None, [])

    service.delete_room(uuid4(), uuid4(), uuid4())

    repository.list_room_storage_paths.assert_not_called()
    assert repository.commit.call_count == 2


def test_storage_failure_keeps_room_and_marks_request_retryable() -> None:
    storage = MagicMock()
    storage.delete.side_effect = RuntimeError("storage unavailable")
    idempotency = MagicMock()
    claim_token = uuid4()
    idempotency.claim.return_value = IdempotencyClaim(
        kind="claimed", claim_token=claim_token
    )
    service, repository = _service(storage, ["user/room/audio.wav"])
    service._idempotency = idempotency
    user_id, room_id, key = uuid4(), uuid4(), uuid4()

    with pytest.raises(ApiError) as captured:
        service.delete_room(user_id, room_id, key)

    assert captured.value.status_code == 503
    assert captured.value.code == "ROOM_STORAGE_DELETE_FAILED"
    assert captured.value.retryable is True
    repository.delete_room.assert_not_called()
    repository.rollback.assert_called_once()
    assert repository.commit.call_count == 2
    idempotency.fail_retryable.assert_called_once_with(
        user_id,
        "room.delete",
        key,
        claim_token,
        "ROOM_STORAGE_DELETE_FAILED",
        service._idempotency_retention_seconds,
    )


def test_completed_room_delete_replays_without_touching_storage_or_database() -> None:
    storage = MagicMock()
    idempotency = MagicMock()
    idempotency.claim.return_value = IdempotencyClaim(
        kind="replay", response_status=204
    )
    service, repository = _service(storage, ["user/room/audio.wav"])
    service._idempotency = idempotency

    service.delete_room(uuid4(), uuid4(), uuid4())

    storage.delete.assert_not_called()
    repository.get_room.assert_not_called()
    repository.delete_room.assert_not_called()
