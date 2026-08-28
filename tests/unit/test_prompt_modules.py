from __future__ import annotations

import inspect

from app.ai.prompts.policies.conversation import (
    CONVERSATION_SUMMARY_INSTRUCTIONS,
    build_conversation_instructions,
)
from app.ai.prompts.policies.tasks import (
    DOCUMENT_ANALYSIS_INSTRUCTIONS,
    EMOTION_ANALYSIS_INSTRUCTIONS,
    INTERVIEW_QUESTION_GENERATION_INSTRUCTIONS,
    SESSION_RESULT_INSTRUCTIONS,
    TURN_FEEDBACK_INSTRUCTIONS,
)
from worker.executors import WorkerExecutors


def test_conversation_prompt_preserves_persona_emotion_policy() -> None:
    prompt = build_conversation_instructions(
        is_interview=False,
        is_closing_response=False,
    )

    assert "사용자 말을 들은 페르소나의 입장" in prompt
    assert "여섯 고정 label" in prompt
    assert "interview_answer_complete와 interview_should_end는 null" in prompt
    assert "기존 요약" in CONVERSATION_SUMMARY_INSTRUCTIONS


def test_interview_prompt_preserves_completion_and_closing_policy() -> None:
    interview_prompt = build_conversation_instructions(
        is_interview=True,
        is_closing_response=False,
    )
    closing_prompt = build_conversation_instructions(
        is_interview=True,
        is_closing_response=True,
    )

    assert "추가 질문은 최대 한 번" in interview_prompt
    assert "마지막으로 더 하실 말씀이 있나요?" in interview_prompt
    assert "질문 목록이나 순서·개수" in interview_prompt
    assert "새 질문을 하지 말고" in closing_prompt
    assert "interview_should_end=true" in closing_prompt


def test_prompt_builder_appends_repair_suffix() -> None:
    suffix = " repair-policy"

    assert build_conversation_instructions(
        is_interview=True,
        is_closing_response=False,
        suffix=suffix,
    ).endswith(suffix)


def test_task_prompt_modules_cover_non_conversation_workers() -> None:
    assert "여섯 고정 label" in EMOTION_ANALYSIS_INSTRUCTIONS
    assert "높임법" in TURN_FEEDBACK_INSTRUCTIONS
    assert "지원 문서" in DOCUMENT_ANALYSIS_INSTRUCTIONS
    assert "{question_count}" in INTERVIEW_QUESTION_GENERATION_INSTRUCTIONS
    assert "강점과 개선점" in SESSION_RESULT_INSTRUCTIONS


def test_worker_executor_does_not_embed_interview_policy_prose() -> None:
    source = inspect.getsource(WorkerExecutors)

    assert "추가 질문은 최대 한 번" not in source
    assert "마지막으로 더 하실 말씀이 있나요?" not in source
