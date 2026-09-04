"""질문 근거 검색을 이력서의 경험·리스크 부분으로 좁히는 경로를 검증한다."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.adapters.interview_provider import (
    AnalysisSections,
    GeneratedQuestion,
    InterviewAnalysisResult,
    InterviewQuestionResult,
    QuestionSourceRef,
)
from app.ai.rag import EVIDENCE_SECTIONS, EvidenceChunk, assign_sections
from app.ai.schemas import EvidenceRelevanceDecision, EvidenceRelevanceResult
from app.schemas.common import JobType
from worker.executors import WorkerExecutors
from worker.queue import ClaimedJob


def test_assign_sections_labels_each_chunk_with_the_closest_section() -> None:
    experience = [1.0, 0.0]
    skills = [0.0, 1.0]

    labels = assign_sections(
        [[0.9, 0.1], [0.1, 0.9], [0.8, 0.2]],
        [("experience", experience), ("skills", skills)],
        fallback="resume",
    )

    assert labels == ["experience", "skills", "experience"]


def test_assign_sections_keeps_the_fallback_when_analysis_extracted_nothing() -> None:
    labels = assign_sections([[1.0, 0.0], [0.0, 1.0]], [], fallback="resume")

    assert labels == ["resume", "resume"]


class _Provider:
    """문서 분석·임베딩·검색을 대신하는 가짜. 호출 인자를 그대로 기록한다."""

    def __init__(self, filtered: list[EvidenceChunk], unfiltered: list[EvidenceChunk]) -> None:
        self.filtered = filtered
        self.unfiltered = unfiltered
        self.retrieve_calls: list[tuple[str, ...] | None] = []
        self.embedded: list[list[str]] = []

    def generate_structured(self, **kwargs: Any) -> Any:
        if kwargs["schema_name"] == "interview_document_analysis":
            return InterviewAnalysisResult(
                sections=AnalysisSections(
                    summary="백엔드 4년차입니다.",
                    skills=["Java", "Spring"],
                    experience=["주문 API 지연을 fetch join 으로 해결했습니다."],
                    risks=["대규모 트래픽 경험이 없습니다."],
                ),
                citations=[],
            )
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
                    for chunk in (self.filtered or self.unfiltered)
                ]
            )
        if kwargs["schema_name"] == "interview_question_generation":
            chunk = (self.filtered or self.unfiltered)[0]
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

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embedded.append(texts)
        # 첫 문장만 경험 쪽으로, 나머지는 기술 쪽으로 기울인 좌표를 준다.
        return [[1.0, 0.0] if index == 0 else [0.0, 1.0] for index in range(len(texts))]

    def retrieve(self, *, sections: tuple[str, ...] | None = None, **_: Any) -> list[EvidenceChunk]:
        self.retrieve_calls.append(sections)
        return self.filtered if sections else self.unfiltered


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


def _chunk(section: str) -> EvidenceChunk:
    return EvidenceChunk(
        id=uuid4(),
        user_id=uuid4(),
        document_id=uuid4(),
        document_version=1,
        text="근거",
        section=section,
        similarity=0.5,
    )


def _job(payload: dict[str, Any]) -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(),
        job_type=JobType.INTERVIEW_CONFIGURATION_GENERATION,
        user_id=uuid4(),
        target_id=uuid4(),
        processing_token=uuid4(),
        attempt_count=1,
        schema_repair_count=0,
        deadline_at=datetime.now(UTC),
        payload=payload,
    )


def _configuration_payload() -> dict[str, Any]:
    return {
        "conditions": {"language": "ko", "difficulty": "junior"},
        "desired_role": "백엔드 개발자",
        "question_count": 3,
        "document_versions": {str(uuid4()): 1},
    }


def test_document_analysis_labels_chunks_with_meaning_not_document_type() -> None:
    provider = _Provider([], [])
    item = _job({"extracted_text": "첫 문단입니다. 둘째 문단입니다.", "document_type": "resume"})

    output = _executors(provider)._document_analysis(item, "")

    sections = [section for _, section, _, _ in output.chunks]
    assert sections and set(sections) <= {"summary", "skills", "experience", "risks"}
    assert "resume" not in sections
    # 청크와 섹션 문장을 한 번에 임베딩해 호출 수를 늘리지 않는다.
    assert len(provider.embedded) == 1


def test_configuration_searches_only_experience_and_risks() -> None:
    provider = _Provider(filtered=[_chunk("experience")], unfiltered=[_chunk("resume")])

    _executors(provider)._configuration(_job(_configuration_payload()), "")

    assert provider.retrieve_calls[0] == EVIDENCE_SECTIONS


def test_configuration_falls_back_to_the_whole_document_for_unlabelled_chunks() -> None:
    # 라벨이 붙기 전에 분석된 문서는 섹션 필터에 한 건도 걸리지 않는다.
    provider = _Provider(filtered=[], unfiltered=[_chunk("resume")])

    _executors(provider)._configuration(_job(_configuration_payload()), "")

    assert provider.retrieve_calls == [EVIDENCE_SECTIONS, None]


def test_configuration_query_is_a_sentence_without_json_or_conditions() -> None:
    provider = _Provider(filtered=[_chunk("experience")], unfiltered=[])

    _executors(provider)._configuration(_job(_configuration_payload()), "")

    query = provider.embedded[0][0]
    assert query.startswith("백엔드 개발자 지원자의 ")
    assert "{" not in query and "junior" not in query and "language" not in query
