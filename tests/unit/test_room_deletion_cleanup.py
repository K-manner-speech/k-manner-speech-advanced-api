from unittest.mock import MagicMock
from uuid import uuid4

from app.services.conversation import SqlConversationService


def _service(storage: object | None, paths: list[str]) -> tuple[SqlConversationService, MagicMock]:
    repository = MagicMock()
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
    repository.commit.assert_called_once()


def test_storage_paths_are_read_before_the_room_row_disappears() -> None:
    storage = MagicMock()
    calls: list[str] = []
    service, repository = _service(storage, [])
    repository.list_room_storage_paths.side_effect = lambda *_: calls.append("list") or []
    repository.delete_room.side_effect = lambda *_: calls.append("delete") or True

    service.delete_room(uuid4(), uuid4(), uuid4())

    # 방을 지우면 message_audio가 함께 사라져 경로를 더 이상 찾을 수 없다.
    assert calls == ["list", "delete"]


def test_room_deletion_works_without_a_storage_client() -> None:
    service, repository = _service(None, [])

    service.delete_room(uuid4(), uuid4(), uuid4())

    repository.list_room_storage_paths.assert_not_called()
    repository.commit.assert_called_once()
