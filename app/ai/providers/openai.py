from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.interfaces import AIProviderError
from app.ai.providers.http import post_json

ResultModel = TypeVar("ResultModel", bound=BaseModel)


class OpenAIResponsesClient:
    _responses_endpoint = "https://api.openai.com/v1/responses"
    _embeddings_endpoint = "https://api.openai.com/v1/embeddings"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
        *,
        reasoning_effort: str = "low",
        max_output_tokens: int = 2000,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens

    def structured_request_body(
        self,
        *,
        instructions: str,
        input_text: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "instructions": instructions,
            "input": input_text,
            "store": False,
            "reasoning": {"effort": self._reasoning_effort},
            "max_output_tokens": self._max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }

    def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        schema_name: str,
        result_type: type[ResultModel],
    ) -> ResultModel:
        payload = post_json(
            self._responses_endpoint,
            self.structured_request_body(
                instructions=instructions,
                input_text=input_text,
                schema_name=schema_name,
                schema=result_type.model_json_schema(),
            ),
            {"Authorization": f"Bearer {self._api_key}"},
            self._timeout_seconds,
            provider="openai_responses",
        )
        output_text = self._extract_output_text(payload)
        try:
            return result_type.model_validate_json(output_text)
        except ValidationError as error:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
            ) from error

    @staticmethod
    def _extract_output_text(payload: dict[str, Any]) -> str:
        for output in payload.get("output", []):
            if not isinstance(output, dict) or output.get("type") != "message":
                continue
            for content in output.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text = content.get("text")
                    if isinstance(text, str):
                        return text
        raise AIProviderError(
            "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
        )


class OpenAIEmbeddingClient:
    _endpoint = "https://api.openai.com/v1/embeddings"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int = 60,
        *,
        dimensions: int = 3072,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding input must contain non-empty text")
        payload = post_json(
            self._endpoint,
            {
                "model": self._model,
                "input": texts,
                "encoding_format": "float",
                "dimensions": self._dimensions,
            },
            {"Authorization": f"Bearer {self._api_key}"},
            self._timeout_seconds,
            provider="openai_embeddings",
        )
        try:
            ordered = sorted(payload["data"], key=lambda item: item["index"])
            embeddings = [item["embedding"] for item in ordered]
            if len(embeddings) != len(texts) or any(
                not isinstance(vector, list) or not vector for vector in embeddings
            ):
                raise ValueError("embedding count mismatch")
            if any(len(vector) != self._dimensions for vector in embeddings):
                raise ValueError("embedding dimension mismatch")
            return embeddings
        except (KeyError, TypeError, ValueError) as error:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
            ) from error
