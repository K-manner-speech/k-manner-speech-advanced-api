from __future__ import annotations

import base64
import json
import logging
from io import BytesIO
from urllib.error import HTTPError
from wave import open as open_wave

import pytest

from app.ai.interfaces import AIProviderError
from app.ai.providers.gemini import GeminiStructuredClient, iter_audio_deltas, pcm_to_wav
from app.ai.providers.openai import OpenAIEmbeddingClient, OpenAIResponsesClient


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


def test_openai_structured_request_bounds_reasoning_and_output_tokens() -> None:
    client = OpenAIResponsesClient("secret", "gpt-test")

    body = client.structured_request_body(
        instructions="지시",
        input_text="입력",
        schema_name="result",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
    )

    assert body["reasoning"] == {"effort": "low"}
    assert body["max_output_tokens"] == 2000


def test_post_json_logs_safe_http_failure_metadata(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from app.ai.providers.http import post_json

    provider_error = HTTPError(
        "https://api.openai.com/v1/responses",
        429,
        "rate limited",
        {"x-request-id": "req_safe_123"},
        BytesIO(b'{"error":{"message":"private-provider-body"}}'),
    )

    def fail_request(*_args: object, **_kwargs: object) -> object:
        raise provider_error

    monkeypatch.setattr("app.ai.providers.http.urlopen", fail_request)

    with caplog.at_level(logging.WARNING), pytest.raises(AIProviderError):
        post_json(
            "https://api.openai.com/v1/responses",
            {"input": "private-resume-input"},
            {"Authorization": "Bearer secret-test-key"},
            30,
            provider="openai_responses",
        )

    assert "provider=openai_responses" in caplog.text
    assert "error_type=HTTPError" in caplog.text
    assert "http_status=429" in caplog.text
    assert "request_id=req_safe_123" in caplog.text
    assert "secret-test-key" not in caplog.text
    assert "private-resume-input" not in caplog.text
    assert "private-provider-body" not in caplog.text


def test_embedding_client_validates_response_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post_json(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

    monkeypatch.setattr("app.ai.providers.openai.post_json", fake_post_json)
    client = OpenAIEmbeddingClient("secret", "text-embedding-3-large", dimensions=3072)

    with pytest.raises(AIProviderError) as raised:
        client.embed(["짧은 벡터"])

    assert raised.value.schema_invalid is True


def test_pcm_to_wav_wraps_mono_24khz_audio() -> None:
    wav = pcm_to_wav(b"\x00\x00\x01\x00", sample_rate=24_000, channels=1, sample_width=2)

    with open_wave(BytesIO(wav), "rb") as audio:
        assert audio.getframerate() == 24_000
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.readframes(2) == b"\x00\x00\x01\x00"


def test_iter_audio_deltas_decodes_only_audio_sse_events() -> None:
    encoded = base64.b64encode(b"\x00\x01\x02\x03").decode()

    chunks = list(iter_audio_deltas([
        'data: {"event_type":"step.delta","delta":{"type":"text","text":"x"}}',
        f'data: {{"event_type":"step.delta","delta":{{"type":"audio","data":"{encoded}"}}}}',
        "data: [DONE]",
    ]))

    assert chunks == [b"\x00\x01\x02\x03"]


def test_gemini_count_tokens_uses_model_tokenizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post_json(
        endpoint: str,
        body: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: int,
        *,
        provider: str = "unknown",
    ) -> dict[str, object]:
        captured.update(
            endpoint=endpoint,
            body=body,
            headers=headers,
            timeout_seconds=timeout_seconds,
            provider=provider,
        )
        return {"totalTokens": 37}

    monkeypatch.setattr("app.ai.providers.gemini.post_json", fake_post_json)
    client = GeminiStructuredClient("secret", "gemini-test", 15)

    assert client.count_tokens("안녕하세요") == 37
    assert str(captured["endpoint"]).endswith("models/gemini-test:countTokens")
    assert "secret" not in json.dumps(captured["body"])
