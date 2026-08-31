from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Iterator
from io import BytesIO
from typing import Any, TypeVar
from urllib.request import Request, urlopen
from wave import open as open_wave

from pydantic import BaseModel, ValidationError

from app.ai.interfaces import AIProviderError
from app.ai.providers.http import post_json

ResultModel = TypeVar("ResultModel", bound=BaseModel)


class GeminiStructuredClient:
    def __init__(self, api_key: str, model: str, timeout_seconds: int) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def count_tokens(self, text: str) -> int:
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:countTokens"
        )
        payload = post_json(
            endpoint,
            {"contents": [{"parts": [{"text": text}]}]},
            {"x-goog-api-key": self._api_key},
            self._timeout_seconds,
            provider="gemini_count_tokens",
        )
        try:
            total = int(payload["totalTokens"])
        except (KeyError, TypeError, ValueError) as error:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
            ) from error
        if total < 0:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
            )
        return total

    def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        schema_name: str,
        result_type: type[ResultModel],
        audio_bytes: bytes | None = None,
        audio_mime_type: str | None = None,
    ) -> ResultModel:
        del schema_name
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent"
        )
        parts: list[dict[str, Any]] = [{"text": input_text}]
        if audio_bytes is not None and audio_mime_type is not None:
            parts.append({"inlineData": {
                "mimeType": audio_mime_type,
                "data": base64.b64encode(audio_bytes).decode(),
            }})
        payload = post_json(
            endpoint,
            {
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": result_type.model_json_schema(),
                },
            },
            {"x-goog-api-key": self._api_key},
            self._timeout_seconds,
            provider="gemini_structured",
        )
        try:
            output = payload["candidates"][0]["content"]["parts"][0]["text"]
            return result_type.model_validate_json(output)
        except (KeyError, IndexError, TypeError, ValidationError) as error:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
            ) from error


class GeminiSpeechClient:
    _endpoint = "https://generativelanguage.googleapis.com/v1beta/interactions"

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 45) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def synthesize(self, text: str, voice: str, delivery_instruction: str) -> bytes:
        payload = post_json(
            self._endpoint,
            {
                "model": self._model,
                "input": f"{delivery_instruction}\n다음 문장만 한국어로 발화하세요: {text}",
                "response_format": {"type": "audio"},
                "generation_config": {"speech_config": [{"voice": voice}]},
            },
            {
                "x-goog-api-key": self._api_key,
                "Api-Revision": "2026-05-20",
            },
            self._timeout_seconds,
            provider="gemini_speech",
        )
        encoded = _find_audio_data(payload)
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
            ) from error
        return pcm_to_wav(pcm, sample_rate=24_000, channels=1, sample_width=2)

    def synthesize_stream(
        self, text: str, voice: str, delivery_instruction: str
    ) -> Iterator[bytes]:
        request = Request(
            self._endpoint,
            data=json.dumps(
                {
                    "model": self._model,
                    "input": f"{delivery_instruction}\n다음 문장만 한국어로 발화하세요: {text}",
                    "response_format": {"type": "audio"},
                    "generation_config": {"speech_config": [{"voice": voice}]},
                    "stream": True,
                },
                ensure_ascii=False,
            ).encode(),
            headers={
                "x-goog-api-key": self._api_key,
                "Api-Revision": "2026-05-20",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                lines = (line.decode("utf-8") for line in response)
                yield from iter_audio_deltas(lines)
        except AIProviderError:
            raise
        except (OSError, TimeoutError, UnicodeDecodeError) as error:
            raise AIProviderError("AI_PROVIDER_UNAVAILABLE", retryable=True) from error


def _find_audio_data(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("type") == "audio" and isinstance(value.get("data"), str):
            return str(value["data"])
        for nested in value.values():
            try:
                return _find_audio_data(nested)
            except AIProviderError:
                continue
    elif isinstance(value, list):
        for nested in value:
            try:
                return _find_audio_data(nested)
            except AIProviderError:
                continue
    raise AIProviderError("AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True)


def iter_audio_deltas(lines: Iterable[str]) -> Iterator[bytes]:
    completed = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data:
            continue
        if data == "[DONE]":
            completed = True
            break
        try:
            event = json.loads(data)
            if event.get("event_type") == "interaction.completed":
                completed = True
                break
            delta = event.get("delta", {})
            if event.get("event_type") != "step.delta" or delta.get("type") != "audio":
                continue
            encoded = delta["data"]
            if not isinstance(encoded, str):
                raise TypeError
            yield base64.b64decode(encoded, validate=True)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
            ) from error
    if not completed:
        raise AIProviderError(
            "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
        )


def pcm_to_wav(
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
) -> bytes:
    output = BytesIO()
    with open_wave(output, "wb") as audio:
        audio.setframerate(sample_rate)
        audio.setnchannels(channels)
        audio.setsampwidth(sample_width)
        audio.writeframes(pcm)
    return output.getvalue()
