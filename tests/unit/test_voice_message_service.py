from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.adapters.storage import StorageObjectStore
from app.core.errors import ApiError
from app.repositories.conversation import InterviewQuestionModeError, InterviewQuestionOrderError
from app.repositories.media import MediaRepository
from app.schemas.rooms import MessageAccepted
from app.services.idempotency import IdempotencyClaim, IdempotencyRepository
from app.services.media import SqlMediaService


def message_row(room_id: object) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": uuid4(), "room_id": room_id, "sequence_no": 1, "sender_type": "user",
        "content": "안녕하세요", "input_mode": "voice", "delivery_status": "sent",
        "reply_to_message_id": None, "created_at": now, "updated_at": now,
    }


def make_service() -> tuple[SqlMediaService, MagicMock, MagicMock, MagicMock]:
    repository = MagicMock(spec=MediaRepository)
    storage = MagicMock(spec=StorageObjectStore)
    idempotency = MagicMock(spec=IdempotencyRepository)
    idempotency.claim.return_value = IdempotencyClaim(kind="claimed", claim_token=uuid4())
    service = SqlMediaService(repository, storage, 4, idempotency, 30, 86_400)
    return service, repository, storage, idempotency


def test_voice_message_accepts_browser_codec_parameter_and_completes_idempotency() -> None:
    service, repository, storage, idempotency = make_service()
    room_id = uuid4()
    repository.create_voice_message.return_value = (
        message_row(room_id), {"id": uuid4(), "type": "conversation_text", "status": "queued"}
    )

    result = service.upload_voice_message(
        uuid4(), room_id, " 안녕하세요 ", None, b"webm", "audio/webm;codecs=opus", uuid4()
    )

    assert isinstance(result, MessageAccepted)
    assert storage.upload.call_args.args[-1] == "audio/webm"
    idempotency.complete.assert_called_once()
    repository.commit.assert_called_once()


def test_voice_message_replays_without_uploading_or_writing() -> None:
    service, repository, storage, idempotency = make_service()
    room_id = uuid4()
    replay = MessageAccepted.model_validate({
        "message": {**message_row(room_id), "emotion": None},
        "job": {"job_id": uuid4(), "type": "conversation_text", "status": "queued"},
    })
    idempotency.claim.return_value = IdempotencyClaim(
        kind="replay", response_status=202, response_body=replay.model_dump(mode="json")
    )

    assert service.upload_voice_message(
        uuid4(), room_id, "안녕하세요", None, b"webm", "audio/webm", uuid4()
    ) == replay
    storage.upload.assert_not_called()
    repository.create_voice_message.assert_not_called()


@pytest.mark.parametrize(
    ("repository_error", "status_code", "code"),
    [
        (LookupError(), 404, "ROOM_NOT_FOUND"),
        (RuntimeError(), 409, "ROOM_NOT_ACTIVE"),
        (OverflowError(), 429, "USER_QUEUE_LIMIT_EXCEEDED"),
        (InterviewQuestionModeError(), 422, "INTERVIEW_QUESTION_MODE_INVALID"),
        (InterviewQuestionOrderError(), 409, "INTERVIEW_QUESTION_OUT_OF_ORDER"),
    ],
)
def test_voice_message_maps_repository_errors_and_removes_uploaded_object(
    repository_error: Exception, status_code: int, code: str
) -> None:
    service, repository, storage, _ = make_service()
    repository.create_voice_message.side_effect = repository_error

    with pytest.raises(ApiError) as captured:
        service.upload_voice_message(
            uuid4(), uuid4(), "안녕하세요", None, b"webm", "audio/webm", uuid4()
        )

    assert captured.value.status_code == status_code
    assert captured.value.code == code
    storage.delete.assert_called_once()
