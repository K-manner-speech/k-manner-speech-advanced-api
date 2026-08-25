from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.common import ErrorEnvelope, Job, JobProgress, JobRef
from app.schemas.feedback import FeedbackScore
from app.schemas.profile import LanguageReplaceRequest
from app.schemas.rooms import MessageCreateRequest, RoomCreateRequest
from app.services.idempotency import validate_client_request_id


def test_error_envelope_uses_safe_complete_shape() -> None:
    request_id = uuid4()

    envelope = ErrorEnvelope(
        code="AUTHENTICATION_REQUIRED",
        message="인증이 필요합니다.",
        request_id=request_id,
        retryable=False,
    )

    assert envelope.model_dump() == {
        "code": "AUTHENTICATION_REQUIRED",
        "message": "인증이 필요합니다.",
        "fields": {},
        "field_errors": [],
        "request_id": request_id,
        "retryable": False,
    }

    with pytest.raises(ValidationError):
        ErrorEnvelope(
            code="BROKEN",
            message="broken",
            request_id="not-a-uuid",
            retryable=False,
            internal_sql="select secret",
        )


@pytest.mark.parametrize(
    "job_type",
    [
        "conversation_text",
        "emotion_analysis",
        "tts_generation",
        "turn_feedback",
        "interview_document_analysis",
        "interview_configuration_generation",
        "session_result_generation",
    ],
)
def test_job_ref_accepts_only_fixed_types_in_queued_state(job_type: str) -> None:
    job_ref = JobRef(job_id=uuid4(), type=job_type, status="queued")

    assert job_ref.status == "queued"

    with pytest.raises(ValidationError):
        JobRef(job_id=uuid4(), type=job_type, status="processing")

    with pytest.raises(ValidationError):
        JobRef(job_id=uuid4(), type="unknown", status="queued")


def test_job_progress_matches_status_and_job_type() -> None:
    now = datetime.now(UTC)
    job = Job(
        id=uuid4(),
        type="emotion_analysis",
        status="processing",
        progress=JobProgress(
            stage="provider_processing",
            completed_units=None,
            total_units=None,
        ),
        error=None,
        result_resource=None,
        created_at=now,
        updated_at=now,
    )

    assert job.progress.stage == "provider_processing"

    with pytest.raises(ValidationError):
        Job(
            id=uuid4(),
            type="emotion_analysis",
            status="queued",
            progress=JobProgress(
                stage="provider_processing",
                completed_units=None,
                total_units=None,
            ),
            error=None,
            result_resource=None,
            created_at=now,
            updated_at=now,
        )

    with pytest.raises(ValidationError):
        Job(
            id=uuid4(),
            type="emotion_analysis",
            status="processing",
            progress=JobProgress(
                stage="storing_audio",
                completed_units=None,
                total_units=None,
            ),
            error=None,
            result_resource=None,
            created_at=now,
            updated_at=now,
        )


def test_language_request_rejects_unsupported_or_server_owned_fields() -> None:
    assert LanguageReplaceRequest(display_language="ko").display_language == "ko"
    assert LanguageReplaceRequest(display_language="en").display_language == "en"

    with pytest.raises(ValidationError):
        LanguageReplaceRequest(display_language="ja")

    with pytest.raises(ValidationError):
        LanguageReplaceRequest(
            display_language="ko",
            user_id=uuid4(),
            onboarding_completed=True,
        )


def test_scenario_room_requires_scenario_and_rejects_owner_fields() -> None:
    request = RoomCreateRequest(
        practice_type="scenario",
        persona_id=uuid4(),
        scenario_id=uuid4(),
    )

    assert request.scenario_id is not None

    with pytest.raises(ValidationError):
        RoomCreateRequest(practice_type="scenario", persona_id=uuid4())

    with pytest.raises(ValidationError):
        RoomCreateRequest(
            practice_type="scenario",
            persona_id=uuid4(),
            scenario_id=uuid4(),
            owner_id=uuid4(),
            status="completed",
        )


def test_message_request_matches_idempotency_key_and_rejects_bad_input() -> None:
    client_request_id = uuid4()
    request = MessageCreateRequest(
        content="면접 답변입니다.",
        input_mode="voice",
        client_request_id=client_request_id,
    )

    validate_client_request_id(request.client_request_id, client_request_id)

    with pytest.raises(ValueError, match="Idempotency-Key"):
        validate_client_request_id(request.client_request_id, uuid4())

    with pytest.raises(ValidationError):
        MessageCreateRequest(
            content="   ",
            input_mode="text",
            client_request_id=uuid4(),
        )

    with pytest.raises(ValidationError):
        MessageCreateRequest(
            content="hello",
            input_mode="keyboard",
            client_request_id=uuid4(),
        )

    with pytest.raises(ValidationError):
        MessageCreateRequest(
            content="hello",
            input_mode="text",
            client_request_id=uuid4(),
            user_id=uuid4(),
        )


@pytest.mark.parametrize("category", ["honorifics", "courtesy", "context_fit", "naturalness"])
@pytest.mark.parametrize("score", [0, 25])
def test_feedback_score_uses_fixed_categories_and_integer_range(
    category: str,
    score: int,
) -> None:
    feedback_score = FeedbackScore(
        category=category,
        score=score,
        max_score=25,
        strength="좋았던 점",
        suggestion="개선 제안",
        original_text="원문",
        recommended_text="추천 표현",
    )

    assert feedback_score.score == score

    for invalid_score in (-1, 1.5, 26):
        with pytest.raises(ValidationError):
            FeedbackScore(
                category=category,
                score=invalid_score,
                max_score=25,
                strength="좋았던 점",
                suggestion="개선 제안",
                original_text="원문",
                recommended_text="추천 표현",
            )

    with pytest.raises(ValidationError):
        FeedbackScore(
            category="consideration",
            score=10,
            max_score=25,
            strength="좋았던 점",
            suggestion="개선 제안",
            original_text="원문",
            recommended_text="추천 표현",
        )
