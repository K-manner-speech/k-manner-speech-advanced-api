from __future__ import annotations

import base64
from io import BytesIO
from typing import Any, TypeVar
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

    def synthesize(self, text: str, voice: str, emotion: str, style: str = "") -> bytes:
        emotion_instructions = {
            "neutral": "차분하고 자연스러운 어조로 말하세요.",
            "happy": "밝고 따뜻하며 기쁜 감정이 느껴지는 어조로 말하세요.",
            "sad": "낮고 부드러우며 아쉬움이 느껴지는 어조로 말하세요.",
            "angry": "불편함이 드러나되 과장하지 않고 단호한 어조로 말하세요.",
            "curious": "관심과 궁금함이 자연스럽게 드러나는 어조로 말하세요.",
            "embarrassment": "조심스럽고 난처한 감정이 느껴지는 어조로 말하세요.",
        }
        delivery_instruction = emotion_instructions.get(
            emotion, emotion_instructions["neutral"]
        )
        # 페르소나 화자 설정이 있으면 감정 지시문 앞에 붙인다.
        if style:
            delivery_instruction = f"{style}, {delivery_instruction}"
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
