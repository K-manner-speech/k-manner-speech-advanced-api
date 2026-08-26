from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.adapters.interview_provider import (
    InterviewProviderError,
    OpenAIInterviewProvider,
)


def test_provider_validates_analysis_and_question_contracts() -> None:
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
                        "source_refs": [{"section": "experience"}],
                        "evaluation_focus": ["역할", "기여도"],
                    },
                    {
                        "sequence": 2,
                        "text": "PostgreSQL 성능 문제를 해결한 경험이 있나요?",
                        "type": "required",
                        "required": True,
                        "source_refs": [{"section": "skills"}],
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
                        "source_refs": [{"section": "experience"}],
                        "evaluation_focus": ["구체성"],
                    }
                ]
            }
        )

    monkeypatch.setattr(provider, "_create_response", fake_response)
    analysis_id = uuid4()

    try:
        provider.generate_questions({"id": analysis_id}, {}, 1)
    except InterviewProviderError as error:
        pytest.fail(f"AC-T3-PROVIDER-SCHEMA: {error}")

    assert str(analysis_id) in captured["input"]
