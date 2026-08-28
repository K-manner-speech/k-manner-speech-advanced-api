from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel


class AIProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        retry_after_seconds: float | None = None,
        schema_invalid: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.schema_invalid = schema_invalid


ModelResult = TypeVar("ModelResult", bound=BaseModel)


class StructuredTextProvider(Protocol):
    def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        schema_name: str,
        result_type: type[ModelResult],
    ) -> ModelResult: ...


class TokenCounter(Protocol):
    def count_tokens(self, text: str) -> int: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SpeechProvider(Protocol):
    def synthesize(self, text: str, voice: str, emotion: str, style: str = "") -> bytes: ...


class ConversationProvider(Protocol):
    def reply(self, context: dict[str, Any]) -> BaseModel: ...
