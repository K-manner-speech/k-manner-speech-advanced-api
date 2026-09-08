from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.repositories.interviews import InterviewRepository
from app.schemas.interviews import InterviewSetupCreateRequest
from app.services.idempotency import (
    IdempotencyClaim,
    IdempotencyRepository,
    request_fingerprint,
)
from app.services.interviews import SqlInterviewService


def make_service(
    repository: MagicMock, idempotency: MagicMock
) -> SqlInterviewService:
    return SqlInterviewService(
        repository,
        MagicMock(),
        pagination_limit=20,
        document_min_text_chars=100,
        idempotency=idempotency,
        idempotency_lease_seconds=30,
        idempotency_retention_seconds=86_400,
    )


def test_create_setup_claims_and_commits_safe_snapshot() -> None:
    user_id = uuid4()
    key = uuid4()
    setup_id = uuid4()
    request = InterviewSetupCreateRequest(
        desired_role="Backend Engineer", application_type="신입"
    )
    row = {
        "id": setup_id,
        "desired_role": "Backend Engineer",
        "application_type": "신입",
        "status": "draft",
        "preparation_progress": 0,
    }
    repository = MagicMock(spec=InterviewRepository)
    repository.create_setup.return_value = row
    idempotency = MagicMock(spec=IdempotencyRepository)
    claim_token = uuid4()
    idempotency.claim.return_value = IdempotencyClaim(
        kind="claimed", claim_token=claim_token
    )

    response = make_service(repository, idempotency).create_setup(user_id, request, key)

    idempotency.claim.assert_called_once_with(
        user_id,
        "interview_setup.create",
        key,
        request_fingerprint(request.model_dump(mode="json")),
        30,
    )
    repository.create_setup.assert_called_once_with(
        user_id, "Backend Engineer", "신입"
    )
    idempotency.complete.assert_called_once_with(
        user_id,
        "interview_setup.create",
        key,
        claim_token,
        201,
        response.model_dump(mode="json"),
        "InterviewSetup.v1",
        86_400,
    )
    repository.commit.assert_called_once_with()
    repository.rollback.assert_not_called()
    assert response.id == setup_id


def test_create_setup_replays_snapshot_without_new_insert() -> None:
    setup_id = uuid4()
    repository = MagicMock(spec=InterviewRepository)
    idempotency = MagicMock(spec=IdempotencyRepository)
    idempotency.claim.return_value = IdempotencyClaim(
        kind="replay",
        response_status=201,
        response_body={
            "id": str(setup_id),
            "desired_role": "Backend Engineer",
            "application_type": None,
            "status": "draft",
            "preparation_progress": 0,
        },
    )

    response = make_service(repository, idempotency).create_setup(
        uuid4(), InterviewSetupCreateRequest(desired_role="Backend Engineer"), uuid4()
    )

    assert response.id == setup_id
    repository.create_setup.assert_not_called()
    idempotency.complete.assert_not_called()
    repository.commit.assert_not_called()


def test_create_setup_rolls_back_when_snapshot_cannot_be_completed() -> None:
    repository = MagicMock(spec=InterviewRepository)
    repository.create_setup.return_value = {
        "id": uuid4(),
        "desired_role": "Backend Engineer",
        "application_type": None,
        "status": "draft",
        "preparation_progress": 0,
    }
    idempotency = MagicMock(spec=IdempotencyRepository)
    idempotency.claim.return_value = IdempotencyClaim(
        kind="claimed", claim_token=uuid4()
    )
    idempotency.complete.side_effect = RuntimeError("idempotency claim was lost")

    with pytest.raises(RuntimeError, match="claim was lost"):
        make_service(repository, idempotency).create_setup(
            uuid4(), InterviewSetupCreateRequest(desired_role="Backend Engineer"), uuid4()
        )

    repository.rollback.assert_called_once_with()
    repository.commit.assert_not_called()
