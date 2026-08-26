from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from app.adapters.interview_provider import InterviewAnalysisResult, InterviewQuestionResult
from app.ai.interfaces import (
    AIProviderError,
    EmbeddingProvider,
    SpeechProvider,
    StructuredTextProvider,
    TokenCounter,
)
from app.ai.rag import EvidenceChunk, chunk_document
from app.ai.schemas import (
    ConversationReply,
    ConversationSummary,
    EmotionAnalysis,
    GeneralFeedback,
    InterviewEvaluation,
    SessionResultOutput,
)
from app.schemas.common import JobType
from worker.queue import ClaimedJob


@dataclass(frozen=True, slots=True)
class DocumentAnalysisOutput:
    analysis: InterviewAnalysisResult
    chunks: list[tuple[int, str, str, list[float]]]


@dataclass(frozen=True, slots=True)
class ConversationOutput:
    reply: ConversationReply
    summary: ConversationSummary | None
    summarized_through_message_id: UUID | None
    recent_message_start_sequence: int | None


@dataclass(frozen=True, slots=True)
class ConfigurationOutput:
    questions: InterviewQuestionResult
    evidence: list[EvidenceChunk]


@dataclass(frozen=True, slots=True)
class TTSOutput:
    wav: bytes
    storage_path: str


@dataclass(frozen=True, slots=True)
class FinalSessionOutput:
    result: SessionResultOutput
    interview_evaluation: InterviewEvaluation | None


class EvidenceRetriever(Protocol):
    def retrieve(
        self,
        *,
        user_id: UUID,
        document_versions: dict[UUID, int],
        query_embedding: list[float],
        threshold: float,
        top_k: int,
    ) -> list[EvidenceChunk]: ...


def validate_question_evidence(
    questions: InterviewQuestionResult,
    evidence: list[EvidenceChunk],
) -> None:
    allowed_refs = {
        (chunk.id, chunk.document_id, chunk.section) for chunk in evidence
    }
    for question in questions.questions:
        if not question.source_refs:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID",
                retryable=False,
                schema_invalid=True,
            )
        if any(
            ref.chunk_id is None
            or ref.document_id is None
            or (ref.chunk_id, ref.document_id, ref.section) not in allowed_refs
            for ref in question.source_refs
        ):
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID",
                retryable=False,
                schema_invalid=True,
            )


def split_conversation_messages(
    messages: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if len(messages) <= 2:
        return [], messages
    return messages[:-2], messages[-2:]


class WorkerExecutors:
    def __init__(
        self,
        *,
        gemini_chat: StructuredTextProvider,
        token_counter: TokenCounter,
        gemini_emotion: StructuredTextProvider,
        gemini_tts: SpeechProvider,
        openai_feedback: StructuredTextProvider,
        openai_interview: StructuredTextProvider,
        embeddings: EmbeddingProvider,
        evidence_retriever: EvidenceRetriever,
        rag_threshold: float,
        context_summary_trigger_tokens: int,
    ) -> None:
        self._gemini_chat = gemini_chat
        self._token_counter = token_counter
        self._gemini_emotion = gemini_emotion
        self._gemini_tts = gemini_tts
        self._openai_feedback = openai_feedback
        self._openai_interview = openai_interview
        self._embeddings = embeddings
        self._evidence_retriever = evidence_retriever
        self._rag_threshold = rag_threshold
        self._context_summary_trigger_tokens = context_summary_trigger_tokens

    def execute(self, item: ClaimedJob, *, repair: bool = False) -> object:
        instructions_suffix = (
            " 이전 출력이 schema 검증에 실패했습니다. 지정된 JSON schema만 정확히 출력하세요."
            if repair
            else ""
        )
        handlers = {
            JobType.CONVERSATION_TEXT: self._conversation,
            JobType.EMOTION_ANALYSIS: self._emotion,
            JobType.TTS_GENERATION: self._tts,
            JobType.TURN_FEEDBACK: self._feedback,
            JobType.INTERVIEW_DOCUMENT_ANALYSIS: self._document_analysis,
            JobType.INTERVIEW_CONFIGURATION_GENERATION: self._configuration,
            JobType.SESSION_RESULT_GENERATION: self._session_result,
        }
        return handlers[item.job_type](item, instructions_suffix)

    def _conversation(self, item: ClaimedJob, suffix: str) -> ConversationOutput:
        input_text = json.dumps(item.payload, ensure_ascii=False, default=str)
        summary = None
        through_message_id = None
        recent_start_sequence = None
        messages = cast(list[dict[str, object]], item.payload["messages"])
        if (
            len(messages) > 2
            and self._token_counter.count_tokens(input_text)
            > self._context_summary_trigger_tokens
        ):
            older, recent = split_conversation_messages(messages)
            if older:
                summary = self._gemini_chat.generate_structured(
                    instructions=(
                        "기존 요약과 오래된 메시지만 사용해 relation, situation, goals, "
                        "agreements, unresolved, important_facts를 갱신하세요. 명시되지 않은 "
                        "사실을 추론하지 마세요." + suffix
                    ),
                    input_text=json.dumps(
                        {
                            "existing_summary": item.payload.get("context_summary"),
                            "older_messages": older,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                    schema_name="conversation_summary",
                    result_type=ConversationSummary,
                )
                last_older = older[-1]
                through_message_id = UUID(str(last_older["id"]))
                recent_start_sequence = int(str(recent[0]["sequence_no"]))
                compact_payload = {
                    **item.payload,
                    "context_summary": summary.model_dump(),
                    "messages": recent,
                }
                input_text = json.dumps(compact_payload, ensure_ascii=False, default=str)
        reply = self._gemini_chat.generate_structured(
            instructions=(
                "한국어 대화 연습 상대 역할을 유지하고, 제공된 사실만 사용해 자연스럽게 한 번 "
                "응답하세요. summary 필드는 null로 반환하세요." + suffix
            ),
            input_text=input_text,
            schema_name="conversation_reply",
            result_type=ConversationReply,
        )
        return ConversationOutput(
            reply=reply,
            summary=summary,
            summarized_through_message_id=through_message_id,
            recent_message_start_sequence=recent_start_sequence,
        )

    def _emotion(self, item: ClaimedJob, suffix: str) -> EmotionAnalysis:
        return self._gemini_emotion.generate_structured(
            instructions=(
                "사용자 발화에서 드러난 감정을 여섯 고정 label 중 하나로 분류하고 짧은 근거를 "
                "제시하세요. 추측을 사실처럼 표현하지 마세요." + suffix
            ),
            input_text=str(item.payload["text"]),
            schema_name="emotion_analysis",
            result_type=EmotionAnalysis,
        )

    def _tts(self, item: ClaimedJob, _suffix: str) -> TTSOutput:
        return TTSOutput(
            wav=self._gemini_tts.synthesize(
                str(item.payload["text"]), str(item.payload.get("voice", "Kore"))
            ),
            storage_path=str(item.payload["storage_path"]),
        )

    def _feedback(self, item: ClaimedJob, suffix: str) -> GeneralFeedback:
        return self._openai_feedback.generate_structured(
            instructions=(
                "한국어 발화를 높임법, 예의와 배려, 상황 적합성, 자연스러움 네 항목으로 "
                "각각 정수 0~25점 평가하세요. 답변에 실제로 드러난 내용만 근거로 삼으세요."
                + suffix
            ),
            input_text=json.dumps(item.payload, ensure_ascii=False, default=str),
            schema_name="turn_feedback",
            result_type=GeneralFeedback,
        )

    def _document_analysis(self, item: ClaimedJob, suffix: str) -> DocumentAnalysisOutput:
        analysis = self._openai_interview.generate_structured(
            instructions=(
                "지원 문서를 면접 준비용으로 구조화하세요. 문서의 사실만 사용하고 인용 근거를 "
                "보존하세요." + suffix
            ),
            input_text=str(item.payload["extracted_text"]),
            schema_name="interview_document_analysis",
            result_type=InterviewAnalysisResult,
        )
        chunks = chunk_document(
            str(item.payload["extracted_text"]),
            maximum_tokens=500,
            overlap_tokens=75,
            section=str(item.payload.get("document_type", "document")),
        )
        embeddings = self._embeddings.embed([chunk.text for chunk in chunks])
        return DocumentAnalysisOutput(
            analysis=analysis,
            chunks=[
                (chunk.index, chunk.section, chunk.text, embedding)
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ],
        )

    def _configuration(self, item: ClaimedJob, suffix: str) -> ConfigurationOutput:
        query = json.dumps(
            {
                "conditions": item.payload["conditions"],
                "role": item.payload.get("desired_role"),
            },
            ensure_ascii=False,
            default=str,
        )
        query_embedding = self._embeddings.embed([query])[0]
        versions = {
            UUID(str(document_id)): int(version)
            for document_id, version in dict(item.payload["document_versions"]).items()
        }
        evidence = self._evidence_retriever.retrieve(
            user_id=item.user_id,
            document_versions=versions,
            query_embedding=query_embedding,
            threshold=self._rag_threshold,
            top_k=5,
        )
        if not evidence:
            raise AIProviderError("INSUFFICIENT_EVIDENCE", retryable=False)
        questions = self._openai_interview.generate_structured(
            instructions=(
                f"제공된 근거만 사용해 면접 질문을 정확히 {item.payload['question_count']}개 "
                "생성하고 각 source ref를 보존하세요." + suffix
            ),
            input_text=json.dumps(
                {
                    "conditions": item.payload["conditions"],
                    "evidence": [
                        {
                            "chunk_id": str(chunk.id),
                            "document_id": str(chunk.document_id),
                            "section": chunk.section,
                            "text": chunk.text,
                        }
                        for chunk in evidence
                    ],
                },
                ensure_ascii=False,
            ),
            schema_name="interview_question_generation",
            result_type=InterviewQuestionResult,
        )
        try:
            questions.validate_count(int(item.payload["question_count"]))
        except ValueError as error:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID",
                retryable=False,
                schema_invalid=True,
            ) from error
        validate_question_evidence(questions, evidence)
        return ConfigurationOutput(questions=questions, evidence=evidence)

    def _session_result(self, item: ClaimedJob, suffix: str) -> FinalSessionOutput:
        generated = self._openai_interview.generate_structured(
            instructions=(
                "대화 결과를 강점과 개선점으로 정리하세요. 면접이면 고정 5개 항목을 각각 "
                "정수 1~20점으로 평가하고 합격·불합격을 판정하지 마세요. 실제 답변만 근거로 "
                "평가하세요." + suffix
            ),
            input_text=json.dumps(item.payload, ensure_ascii=False, default=str),
            schema_name="session_result",
            result_type=SessionResultOutput,
        )
        evaluation = None
        if bool(item.payload.get("is_interview")):
            try:
                evaluation = InterviewEvaluation.from_scores(
                    generated.interview_scores,
                    generated.summary,
                )
            except ValueError as error:
                raise AIProviderError(
                    "AI_PROVIDER_SCHEMA_INVALID",
                    retryable=False,
                    schema_invalid=True,
                ) from error
        return FinalSessionOutput(result=generated, interview_evaluation=evaluation)
