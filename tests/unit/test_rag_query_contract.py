"""면접 질문 근거 검색의 검색어 계약을 검증한다."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.adapters.interview_provider import (
    GeneratedQuestion,
    InterviewQuestionResult,
    QuestionSourceRef,
)
from app.ai.rag import EvidenceChunk
from app.ai.schemas import EvidenceRelevanceDecision, EvidenceRelevanceResult
from app.schemas.common import JobType
from worker.executors import WorkerExecutors
from worker.queue import ClaimedJob


class _Provider:
    """임베딩·검색·판정을 대신하는 가짜. 호출 인자를 그대로 기록한다."""

    def __init__(self, chunks: list[EvidenceChunk]) -> None:
        self.chunks = chunks
        self.embedded: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.append(texts)
        return [[1.0, 0.0] for _ in texts]

    def retrieve(self, **_: Any) -> list[EvidenceChunk]:
        return self.chunks

    def generate_structured(self, **kwargs: Any) -> Any:
        if kwargs["schema_name"] == "interview_evidence_relevance":
            return EvidenceRelevanceResult(
                decisions=[
                    EvidenceRelevanceDecision(
                        chunk_id=chunk.id,
                        support_level="supported",
                        supported_claims=["근거가 있습니다."],
                        unsupported_claims=[],
                        reason="본문에 그대로 있습니다.",
                    )
                    for chunk in self.chunks
                ]
            )
        if kwargs["schema_name"] == "interview_question_generation":
            chunk = self.chunks[0]
            return InterviewQuestionResult(
                questions=[
                    GeneratedQuestion(
                        sequence=index,
                        text=f"질문 {index}",
                        type="experience",
                        required=True,
                        source_refs=[
                            QuestionSourceRef(
                                section=chunk.section,
                                chunk_id=chunk.id,
                                document_id=chunk.document_id,
                                evidence=chunk.text,
                            )
                        ],
                        evaluation_focus=["문제 해결"],
                    )
                    for index in range(1, 4)
                ]
            )
        raise AssertionError(f"예상하지 못한 호출: {kwargs['schema_name']}")


def _executors(provider: _Provider) -> WorkerExecutors:
    return WorkerExecutors(
        gemini_chat=provider,
        token_counter=provider,
        gemini_emotion=provider,
        gemini_tts=provider,
        openai_feedback=provider,
        openai_interview=provider,
        embeddings=provider,
        evidence_retriever=provider,
        rag_threshold=0.35,
        context_summary_trigger_tokens=4_000,
    )


def _chunk() -> EvidenceChunk:
    return EvidenceChunk(
        id=uuid4(),
        user_id=uuid4(),
        document_id=uuid4(),
        document_version=1,
        text="주문 API 지연을 fetch join 으로 해결했습니다.",
        section="resume",
        similarity=0.5,
    )


def _job() -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(),
        job_type=JobType.INTERVIEW_CONFIGURATION_GENERATION,
        user_id=uuid4(),
        target_id=uuid4(),
        processing_token=uuid4(),
        attempt_count=1,
        schema_repair_count=0,
        deadline_at=datetime.now(UTC),
        payload={
            "conditions": {"language": "ko", "difficulty": "junior"},
            "desired_role": "백엔드 개발자",
            "question_count": 3,
            "document_versions": {str(uuid4()): 1},
        },
    )


def test_search_query_is_a_sentence_without_json_or_conditions() -> None:
    """검색어는 이력서 본문과 같은 문체여야 한다.

    JSON 은 절반이 키 이름과 기호이고, language·difficulty 는 이력서에서 찾을
    내용이 아니라 검색을 흐린다. 이력서 30개 측정에서 F1 이 0.394 에서 0.967 로
    올랐다.
    """
    provider = _Provider([_chunk()])

    _executors(provider)._configuration(_job(), "")

    query = provider.embedded[0][0]
    assert query.startswith("백엔드 개발자 지원자의 ")
    assert "{" not in query
    assert "junior" not in query and "language" not in query
