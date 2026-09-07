"""근거 판정(재랭킹)의 계약을 검증한다."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.adapters.interview_provider import (
    GeneratedQuestion,
    InterviewQuestionResult,
    QuestionSourceRef,
)
from app.ai.rag import EvidenceChunk
from app.ai.schemas import EvidenceRelevanceDecision, EvidenceRelevanceResult
from app.schemas.common import JobType
from worker.executors import AIProviderError, WorkerExecutors
from worker.queue import ClaimedJob


def _chunk(text: str = "주문 API 지연을 fetch join 으로 해결했습니다.") -> EvidenceChunk:
    return EvidenceChunk(
        id=uuid4(), user_id=uuid4(), document_id=uuid4(), document_version=1,
        text=text, section="resume", similarity=0.5,
    )


class _Provider:
    """판정 결과를 호출 순서대로 미리 정해 두는 가짜."""

    def __init__(self, chunks: list[EvidenceChunk], verdicts: list[str]) -> None:
        self.chunks = chunks
        self.verdicts = list(verdicts)
        self.relevance_inputs: list[dict[str, Any]] = []
        self.question_inputs: list[dict[str, Any]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def retrieve(self, **_: Any) -> list[EvidenceChunk]:
        return self.chunks

    def generate_structured(self, **kwargs: Any) -> Any:
        payload = json.loads(kwargs["input_text"])
        if kwargs["schema_name"] == "interview_evidence_relevance":
            self.relevance_inputs.append(payload)
            level = self.verdicts.pop(0) if self.verdicts else "supported"
            return EvidenceRelevanceResult(
                decisions=[
                    EvidenceRelevanceDecision(
                        chunk_id=chunk.id, support_level=level,
                        supported_claims=[] if level == "unsupported" else ["물을 수 있음"],
                        unsupported_claims=["물을 수 없음"] if level != "supported" else [],
                        reason="판정",
                    )
                    for chunk in self.chunks
                ]
            )
        if kwargs["schema_name"] == "interview_question_generation":
            self.question_inputs.append(payload)
            chunk = self.chunks[0]
            return InterviewQuestionResult(
                questions=[
                    GeneratedQuestion(
                        sequence=index, text=f"질문 {index}", type="experience",
                        required=True,
                        source_refs=[QuestionSourceRef(
                            section=chunk.section, chunk_id=chunk.id,
                            document_id=chunk.document_id, evidence=chunk.text)],
                        evaluation_focus=["문제 해결"],
                    )
                    for index in range(1, 4)
                ]
            )
        raise AssertionError(f"예상하지 못한 호출: {kwargs['schema_name']}")


def _executors(provider: _Provider) -> WorkerExecutors:
    return WorkerExecutors(
        gemini_chat=provider, token_counter=provider, gemini_emotion=provider,
        gemini_tts=provider, openai_feedback=provider, openai_interview=provider,
        embeddings=provider, evidence_retriever=provider,
        rag_threshold=0.35, context_summary_trigger_tokens=4_000,
    )


def _job() -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(), job_type=JobType.INTERVIEW_CONFIGURATION_GENERATION,
        user_id=uuid4(), target_id=uuid4(), processing_token=uuid4(),
        attempt_count=1, schema_repair_count=0, deadline_at=datetime.now(UTC),
        payload={
            "conditions": {"language": "ko", "difficulty": "junior"},
            "desired_role": "백엔드 개발자",
            "question_count": 3,
            "document_versions": {str(uuid4()): 1},
        },
    )


def test_relevance_judgement_does_not_receive_the_question_conditions() -> None:
    """language·difficulty 로는 청크를 판정할 수 없다.

    판정할 것이 없는 기준을 주면 같은 입력에도 답이 흔들린다. 조건은 질문을
    만들 때만 쓰고, 판정에는 직무만 넘긴다.
    """
    provider = _Provider([_chunk()], ["supported"])

    _executors(provider)._configuration(_job(), "")

    judged = provider.relevance_inputs[0]
    assert "conditions" not in judged
    assert judged["desired_role"] == "백엔드 개발자"
    # 조건은 질문 생성에는 그대로 필요하다.
    assert provider.question_inputs[0]["conditions"] == {
        "language": "ko", "difficulty": "junior"
    }


def test_total_collapse_is_judged_once_more_instead_of_being_overridden() -> None:
    """판정이 통째로 무너지면 등급을 조작하지 않고 다시 묻는다."""
    provider = _Provider([_chunk(), _chunk("정산 배치 중복을 막았습니다.")],
                         ["unsupported", "supported"])

    output = _executors(provider)._configuration(_job(), "")

    assert len(provider.relevance_inputs) == 2
    assert len(output.evidence) == 2


def test_collapsing_twice_fails_instead_of_inventing_evidence() -> None:
    provider = _Provider([_chunk()], ["unsupported", "unsupported"])

    with pytest.raises(AIProviderError) as error:
        _executors(provider)._configuration(_job(), "")

    assert error.value.code == "INSUFFICIENT_EVIDENCE"
    assert len(provider.relevance_inputs) == 2
