from __future__ import annotations

import json
import logging
from io import BytesIO
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from app.adapters.interview_provider import (
    InterviewProviderError,
    OpenAIInterviewProvider,
)


def test_interview_provider_defaults_to_120_second_timeout() -> None:
    provider = OpenAIInterviewProvider("test-key", "test-model")

    assert provider._timeout_seconds == 120


def test_interview_provider_logs_safe_http_failure_metadata(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = OpenAIInterviewProvider("secret-test-key", "test-model")
    provider_error = HTTPError(
        "https://api.openai.com/v1/responses",
        429,
        "rate limited",
        {"x-request-id": "req_safe_123"},
        BytesIO(b'{"error":{"message":"private-provider-body"}}'),
    )

    def fail_request(*_args: object, **_kwargs: object) -> object:
        raise provider_error

    monkeypatch.setattr("app.adapters.interview_provider.urlopen", fail_request)

    with caplog.at_level(logging.WARNING), pytest.raises(InterviewProviderError):
        provider.analyze_document("private-resume-input")

    assert "provider=openai_interview" in caplog.text
    assert "error_type=HTTPError" in caplog.text
    assert "http_status=429" in caplog.text
    assert "request_id=req_safe_123" in caplog.text
    assert "secret-test-key" not in caplog.text
    assert "private-resume-input" not in caplog.text
    assert "private-provider-body" not in caplog.text


def test_interview_provider_bounds_reasoning_and_output_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {
                                            "sections": {
                                                "summary": "요약",
                                                "skills": [],
                                                "experience": [],
                                                "risks": [],
                                            },
                                            "citations": [],
                                        }
                                    ),
                                }
                            ],
                        }
                    ]
                }
            ).encode()

    def capture_request(request: object, *, timeout: int) -> FakeResponse:
        captured["body"] = json.loads(request.data)  # type: ignore[attr-defined]
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.adapters.interview_provider.urlopen", capture_request)

    OpenAIInterviewProvider("test-key", "test-model").analyze_document("resume")

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["reasoning"] == {"effort": "low"}
    assert body["max_output_tokens"] == 2000
    assert body["text"]["format"]["strict"] is True


def test_provider_validates_analysis_and_question_contracts() -> None:
    chunk_id = uuid4()
    analysis = OpenAIInterviewProvider.parse_analysis(
        json.dumps(
            {
                "sections": {
                    "summary": "백엔드 개발 경험",
                    "skills": ["Python", "PostgreSQL"],
                    "experience": ["API 개발"],
                    "risks": [],
                },
                "citations": [
                    {"section": "experience", "evidence": "FastAPI 기반 API를 개발했습니다."}
                ],
            },
            ensure_ascii=False,
        )
    )
    questions = OpenAIInterviewProvider.parse_questions(
        json.dumps(
            {
                "questions": [
                    {
                        "sequence": 1,
                        "text": "FastAPI 프로젝트에서 맡은 역할을 설명해 주세요.",
                        "type": "required",
                        "required": True,
                        "source_refs": [{"chunk_id": str(chunk_id), "section": "experience"}],
                        "evaluation_focus": ["역할", "기여도"],
                    },
                    {
                        "sequence": 2,
                        "text": "PostgreSQL 성능 문제를 해결한 경험이 있나요?",
                        "type": "required",
                        "required": True,
                        "source_refs": [{"chunk_id": str(chunk_id), "section": "skills"}],
                        "evaluation_focus": ["문제 해결"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        question_count=2,
    )

    assert analysis.sections.summary == "백엔드 개발 경험"
    assert len(analysis.citations) == 1
    assert [question.sequence for question in questions.questions] == [1, 2]
    assert len(questions.questions) == 2, "AC-T3-PROVIDER-SCHEMA"


@pytest.mark.parametrize(
    "payload,count",
    [
        ("not-json", 1),
        ('{"questions": []}', 1),
        (
            '{"questions":[{"sequence":2,"text":"질문","type":"required",'
            '"required":true,"source_refs":[],"evaluation_focus":["태도"]}]}',
            1,
        ),
    ],
)
def test_provider_rejects_malformed_or_mismatched_questions(payload: str, count: int) -> None:
    with pytest.raises(InterviewProviderError) as raised:
        OpenAIInterviewProvider.parse_questions(payload, question_count=count)

    assert raised.value.code == "INTERVIEW_PROVIDER_SCHEMA_INVALID"
    assert "not-json" not in str(raised.value)


def test_question_request_serializes_database_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIInterviewProvider("test-key", "test-model")
    captured: dict[str, str] = {}

    def fake_response(**kwargs: object) -> str:
        captured["input"] = str(kwargs["input_text"])
        return json.dumps(
            {
                "questions": [
                    {
                        "sequence": 1,
                        "text": "경험을 설명해 주세요.",
                        "type": "required",
                        "required": True,
                        "source_refs": [{"chunk_id": str(analysis_id), "section": "experience"}],
                        "evaluation_focus": ["구체성"],
                    }
                ]
            }
        )

    monkeypatch.setattr(provider, "_create_response", fake_response)
    analysis_id = uuid4()

    try:
        provider.generate_questions(
            {"id": analysis_id, "evidence": [{"chunk_id": analysis_id, "content": "경험"}]},
            {},
            1,
        )
    except InterviewProviderError as error:
        pytest.fail(f"AC-T3-PROVIDER-SCHEMA: {error}")

    assert str(analysis_id) in captured["input"]
