from __future__ import annotations

import json
from io import BytesIO
from wave import open as open_wave

import pytest

from app.ai.providers.gemini import GeminiStructuredClient, pcm_to_wav
from app.ai.providers.openai import OpenAIResponsesClient


def test_openai_structured_request_disables_storage() -> None:
    client = OpenAIResponsesClient("secret", "gpt-test")

    body = client.structured_request_body(
        instructions="안전한 지시",
        input_text="입력",
        schema_name="result",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
    )

    assert body["store"] is False
    assert body["text"]["format"]["type"] == "json_schema"
    assert "secret" not in json.dumps(body)


def test_pcm_to_wav_wraps_mono_24khz_audio() -> None:
    wav = pcm_to_wav(b"\x00\x00\x01\x00", sample_rate=24_000, channels=1, sample_width=2)

    with open_wave(BytesIO(wav), "rb") as audio:
        assert audio.getframerate() == 24_000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.readframes(2) == b"\x00\x00\x01\x00"


def test_gemini_count_tokens_uses_model_tokenizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post_json(
        endpoint: str,
        body: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, object]:
        captured.update(
            endpoint=endpoint,
            body=body,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
        return {"totalTokens": 37}

    monkeypatch.setattr("app.ai.providers.gemini.post_json", fake_post_json)
    client = GeminiStructuredClient("secret", "gemini-test", 15)

    assert client.count_tokens("안녕하세요") == 37
    assert str(captured["endpoint"]).endswith("models/gemini-test:countTokens")
    assert "secret" not in json.dumps(captured["body"])
