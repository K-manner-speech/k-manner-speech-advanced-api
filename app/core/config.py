from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr
    supabase_url: str
    supabase_jwt_issuer: str
    supabase_jwt_audience: str
    supabase_service_role_key: SecretStr
    cors_allowed_origins: list[str]

    gemini_api_key: SecretStr
    openai_api_key: SecretStr
    gemini_chat_model: str
    gemini_tts_model: str
    gemini_emotion_model: str
    openai_feedback_model: str
    openai_interview_model: str
    openai_embedding_model: str

    queue_names: list[str]
    pagination_limit: int = Field(gt=0)
    user_queue_limit: int = Field(gt=0)
    worker_concurrency: int = Field(gt=0)
    worker_visibility_timeout_seconds: int = Field(gt=60)
    rag_similarity_threshold: float = Field(gt=0, le=1)
    context_summary_trigger_tokens: int = Field(gt=0)
    document_min_text_chars: int = Field(gt=0)
    worker_heartbeat_ttl_seconds: int = Field(gt=0)
    idempotency_lease_seconds: int = Field(gt=0)
    idempotency_retention_seconds: int = Field(gt=0)

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("at least one CORS origin is required")

        for origin in origins:
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS values must be exact HTTP(S) origins")
        return origins

    @field_validator("queue_names")
    @classmethod
    def validate_queue_names(cls, queue_names: list[str]) -> list[str]:
        if not queue_names or any(not name.strip() for name in queue_names):
            raise ValueError("queue names must be non-empty")
        if len(queue_names) != len(set(queue_names)):
            raise ValueError("queue names must be unique")
        required = {
            "conversation_text",
            "conversation_text_dlq",
            "interactive_ai",
            "interactive_ai_dlq",
            "document_analysis",
            "document_analysis_dlq",
        }
        if set(queue_names) != required:
            raise ValueError("queue names must match the required queues and DLQs")
        return queue_names

    @field_validator("openai_embedding_model")
    @classmethod
    def validate_embedding_model(cls, model: str) -> str:
        if model != "text-embedding-3-large":
            raise ValueError("embedding model must match the architecture contract")
        return model
