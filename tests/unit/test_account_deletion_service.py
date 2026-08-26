from unittest.mock import MagicMock, call
from uuid import uuid4

import pytest

from app.adapters.account_auth import AccountAuthGateway, AuthReconfirmationError
from app.adapters.storage import StorageObjectStore
from app.core.errors import ApiError
from app.repositories.account import AccountDeletionRepository, StoredObject
from app.services.account import SqlAccountDeletionService
from app.services.idempotency import IdempotencyClaim, IdempotencyRepository


def make_service(
    repository: MagicMock,
    storage: MagicMock,
    auth: MagicMock,
    idempotency: MagicMock,
) -> SqlAccountDeletionService:
    return SqlAccountDeletionService(
        repository,
        storage,
        auth,
        idempotency,
        idempotency_lease_seconds=30,
        idempotency_retention_seconds=86_400,
    )


def test_account_delete_reconfirms_then_removes_storage_and_auth_user() -> None:
    user_id = uuid4()
    key = uuid4()
    claim_token = uuid4()
    objects = [
        StoredObject("interview-documents", f"{user_id}/setup/resume.pdf"),
        StoredObject("message-audio", f"{user_id}/room/message.wav"),
    ]
    repository = MagicMock(spec=AccountDeletionRepository)
    repository.list_storage_objects.side_effect = [objects, []]
    storage = MagicMock(spec=StorageObjectStore)
    auth = MagicMock(spec=AccountAuthGateway)
    idempotency = MagicMock(spec=IdempotencyRepository)
    idempotency.claim.return_value = IdempotencyClaim(
        kind="claimed", claim_token=claim_token
    )

    make_service(repository, storage, auth, idempotency).delete_account(
        user_id, "access-token", key
    )

    auth.reconfirm_user.assert_called_once_with("access-token", user_id)
    idempotency.claim.assert_called_once()
    assert repository.method_calls[:4] == [
        call.commit(),
        call.list_storage_objects(user_id),
        call.cancel_jobs_and_cleanup_queues(user_id),
        call.commit(),
    ]
    assert storage.delete.call_args_list == [
        call("interview-documents", f"{user_id}/setup/resume.pdf"),
        call("message-audio", f"{user_id}/room/message.wav"),
    ]
    assert repository.method_calls[4:] == [
        call.list_storage_objects(user_id),
        call.commit(),
    ]
    auth.delete_user.assert_called_once_with(user_id)
    idempotency.complete.assert_not_called()


def test_account_delete_stops_before_claim_when_reconfirmation_fails() -> None:
    repository = MagicMock(spec=AccountDeletionRepository)
    storage = MagicMock(spec=StorageObjectStore)
    auth = MagicMock(spec=AccountAuthGateway)
    auth.reconfirm_user.side_effect = AuthReconfirmationError()
    idempotency = MagicMock(spec=IdempotencyRepository)

    with pytest.raises(ApiError) as captured:
        make_service(repository, storage, auth, idempotency).delete_account(
            uuid4(), "expired-token", uuid4()
        )

    assert captured.value.status_code == 401
    assert captured.value.code == "ACCOUNT_RECONFIRMATION_FAILED"
    idempotency.claim.assert_not_called()
    storage.delete.assert_not_called()
    auth.delete_user.assert_not_called()


def test_account_delete_records_retryable_failure_without_deleting_auth_user() -> None:
    user_id = uuid4()
    key = uuid4()
    claim_token = uuid4()
    repository = MagicMock(spec=AccountDeletionRepository)
    repository.list_storage_objects.return_value = [
        StoredObject("interview-documents", f"{user_id}/resume.pdf")
    ]
    storage = MagicMock(spec=StorageObjectStore)
    storage.delete.side_effect = RuntimeError("storage failed")
    auth = MagicMock(spec=AccountAuthGateway)
    idempotency = MagicMock(spec=IdempotencyRepository)
    idempotency.claim.return_value = IdempotencyClaim(
        kind="claimed", claim_token=claim_token
    )

    with pytest.raises(ApiError) as captured:
        make_service(repository, storage, auth, idempotency).delete_account(
            user_id, "access-token", key
        )

    assert captured.value.status_code == 503
    assert captured.value.retryable is True
    idempotency.fail_retryable.assert_called_once_with(
        user_id,
        "account.delete",
        key,
        claim_token,
        "ACCOUNT_DELETION_INCOMPLETE",
        86_400,
    )
    auth.delete_user.assert_not_called()


def test_account_delete_does_not_delete_auth_user_while_objects_remain() -> None:
    user_id = uuid4()
    remaining = StoredObject("message-audio", f"{user_id}/remaining.wav")
    repository = MagicMock(spec=AccountDeletionRepository)
    repository.list_storage_objects.side_effect = [[remaining], [remaining]]
    storage = MagicMock(spec=StorageObjectStore)
    auth = MagicMock(spec=AccountAuthGateway)
    idempotency = MagicMock(spec=IdempotencyRepository)
    idempotency.claim.return_value = IdempotencyClaim(
        kind="claimed", claim_token=uuid4()
    )

    with pytest.raises(ApiError) as captured:
        make_service(repository, storage, auth, idempotency).delete_account(
            user_id, "access-token", uuid4()
        )

    assert captured.value.code == "ACCOUNT_DELETION_INCOMPLETE"
    auth.delete_user.assert_not_called()
