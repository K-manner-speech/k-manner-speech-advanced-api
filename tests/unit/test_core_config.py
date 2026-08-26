from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import AppSettings


def complete_settings() -> dict[str, object]:
    return {
        "database_url": "postgresql+psycopg://postgres:secret@localhost:5432/postgres",
        "supabase_url": "https://project.supabase.co",
        "supabase_jwt_issuer": "https://project.supabase.co/auth/v1",
        "supabase_jwt_audience": "authenticated",
        "supabase_service_role_key": "server-secret",
        "cors_allowed_origins": ["http://localhost:5173"],
        "gemini_api_key": "gemini-secret",
        "openai_api_key": "openai-secret",
        "gemini_chat_model": "chat-model",
        "gemini_tts_model": "tts-model",
        "gemini_emotion_model": "emotion-model",
        "openai_feedback_model": "feedback-model",
        "openai_interview_model": "interview-model",
        "openai_embedding_model": "text-embedding-3-large",
        "queue_names": [
            "conversation_text",
            "conversation_text_dlq",
            "interactive_ai",
            "interactive_ai_dlq",
            "document_analysis",
            "document_analysis_dlq",
        ],
        "pagination_limit": 20,
        "user_queue_limit": 4,
        "worker_concurrency": 2,
        "worker_visibility_timeout_seconds": 65,
        "rag_similarity_threshold": 0.7,
        "context_summary_trigger_tokens": 4000,
        "document_min_text_chars": 100,
        "worker_heartbeat_ttl_seconds": 30,
        "idempotency_lease_seconds": 30,
        "idempotency_retention_seconds": 86400,
    }


def test_settings_require_every_value_without_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = complete_settings()
    for field_name in values:
        monkeypatch.delenv(field_name.upper(), raising=False)
    settings = AppSettings(_env_file=None, **values)

    assert settings.pagination_limit == 20
    assert settings.openai_embedding_model == "text-embedding-3-large"

    for field_name in values:
        incomplete = values.copy()
        incomplete.pop(field_name)
        with pytest.raises(ValidationError):
            AppSettings(_env_file=None, **incomplete)


@pytest.mark.parametrize(
    "invalid_origin",
    [
        "*",
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com?query=1",
        "https://example.com#fragment",
    ],
)
def test_cors_rejects_non_origin_values(invalid_origin: str) -> None:
    values = complete_settings()
    values["cors_allowed_origins"] = [invalid_origin]

    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, **values)


def test_embedding_model_is_fixed_by_architecture_contract() -> None:
    values = complete_settings()
    values["openai_embedding_model"] = "gpt-5.6-luna"

    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, **values)


def test_worker_visibility_must_outlive_longest_job_deadline() -> None:
    values = complete_settings()
    values["worker_visibility_timeout_seconds"] = 60

    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, **values)


def test_local_worker_and_jwt_defaults_are_safe_and_extensible() -> None:
    settings = AppSettings(_env_file=None, **complete_settings())

    assert settings.required_worker_queues == ["document_analysis"]
    assert settings.jwt_leeway_seconds == 5

    values = complete_settings()
    values["required_worker_queues"] = ["document_analysis", "conversation_text"]
    assert AppSettings(_env_file=None, **values).required_worker_queues == [
        "document_analysis",
        "conversation_text",
    ]

    values["required_worker_queues"] = ["document_analysis_dlq"]
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, **values)

    values = complete_settings()
    values["jwt_leeway_seconds"] = -1
    with pytest.raises(ValidationError):
        AppSettings(_env_file=None, **values)
