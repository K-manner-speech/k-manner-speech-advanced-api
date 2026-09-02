from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.interfaces import AIProviderError
from app.ai.schemas import GeneralSessionResultOutput, InterviewSessionResultOutput
from app.schemas.common import JobType
from worker.executors import WorkerExecutors
from worker.queue import ClaimedJob


class _ResultProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_structured(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        result_type = kwargs["result_type"]
        assert isinstance(result_type, type)
        payload: dict[str, object] = {"summary": "요약", "items": []}
        if result_type.__name__ == "InterviewSessionResultOutput":
            payload["interview_scores"] = [
                {
                    "category": category,
                    "score": 12,
                    "strength": None,
                    "suggestion": None,
                    "evidence": "답변 근거",
                }
                for category in (
                    "question_understanding_fit",
                    "answer_structure",
                    "specificity_evidence",
                    "job_fit_problem_solving",
                    "delivery_attitude",
                )
            ]
        return result_type.model_validate(payload)

    def count_tokens(self, _text: str) -> int:
        return 1


def _executors(provider: _ResultProvider) -> WorkerExecutors:
    return WorkerExecutors(
        gemini_chat=provider,
        token_counter=provider,
        gemini_emotion=provider,
        gemini_tts=provider,
        openai_feedback=provider,
        openai_interview=provider,
        embeddings=provider,
        evidence_retriever=provider,
        rag_threshold=0.7,
        context_summary_trigger_tokens=4_000,
    )


def _item(practice_type: str) -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(),
        job_type=JobType.SESSION_RESULT_GENERATION,
        user_id=uuid4(),
        target_id=uuid4(),
        processing_token=uuid4(),
        attempt_count=1,
        schema_repair_count=0,
        deadline_at=datetime.now(UTC),
        payload={
            "practice_type": practice_type,
            "is_interview": practice_type == "interview",
            "messages": [],
            "success_conditions": [],
            "turn_scores": [],
        },
    )


@pytest.mark.parametrize(
    ("practice_type", "schema_name", "result_type_name"),
    [
        ("free_chat", "session_result_free_chat", "GeneralSessionResultOutput"),
        ("scenario", "session_result_scenario", "GeneralSessionResultOutput"),
        ("interview", "session_result_interview", "InterviewSessionResultOutput"),
    ],
)
def test_session_result_uses_a_type_specific_prompt_and_schema(
    practice_type: str,
    schema_name: str,
    result_type_name: str,
) -> None:
    provider = _ResultProvider()

    _executors(provider).execute(_item(practice_type))

    call = provider.calls[-1]
    assert call["schema_name"] == schema_name
    assert call["result_type"].__name__ == result_type_name


def test_unknown_practice_type_is_rejected_instead_of_falling_back() -> None:
    provider = _ResultProvider()

    with pytest.raises(AIProviderError) as caught:
        _executors(provider).execute(_item("unknown"))

    assert caught.value.retryable is False
    assert provider.calls == []


def test_type_specific_prompts_do_not_mix_evaluation_domains() -> None:
    composer = _executors(_ResultProvider())._prompt_composer

    free_chat = composer.task_instruction("session_result_free_chat")
    scenario = composer.task_instruction("session_result_scenario")
    interview = composer.task_instruction("session_result_interview")

    for category in ("honorifics", "courtesy", "context_fit", "naturalness"):
        assert category in free_chat
        assert category in scenario
        assert category not in interview
    assert "success_conditions" not in free_chat
    assert "success_conditions" in scenario
    assert "source_evidence" not in free_chat
    assert "source_evidence" not in scenario
    assert "source_evidence" in interview


def test_general_and_interview_output_contracts_reject_cross_type_fields() -> None:
    with pytest.raises(ValidationError):
        GeneralSessionResultOutput.model_validate(
            {"summary": "일반 결과", "items": [], "interview_scores": []}
        )

    with pytest.raises(ValidationError):
        InterviewSessionResultOutput.model_validate(
            {"summary": "면접 결과", "items": []}
        )
