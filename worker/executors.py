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
from app.ai.prompts.conversation import (
    CONVERSATION_SUMMARY_INSTRUCTIONS,
    build_conversation_instructions,
)
from app.ai.prompts.tasks import (
    DOCUMENT_ANALYSIS_INSTRUCTIONS,
    EMOTION_ANALYSIS_INSTRUCTIONS,
    INTERVIEW_QUESTION_GENERATION_INSTRUCTIONS,
    SESSION_RESULT_INSTRUCTIONS,
    TURN_FEEDBACK_INSTRUCTIONS,
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
                    instructions=CONVERSATION_SUMMARY_INSTRUCTIONS + suffix,
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
        is_interview = item.payload.get("room", {}).get("practice_type") == "interview"
        is_closing_response = bool(item.payload.get("interview_closing_response"))
        generation_kwargs: dict[str, object] = {
            "instructions": build_conversation_instructions(
                is_interview=is_interview,
                is_closing_response=is_closing_response,
                suffix=suffix,
            ),
            "input_text": input_text,
            "schema_name": "conversation_reply",
            "result_type": ConversationReply,
        }
        if item.payload.get("audio_bytes") is not None:
            generation_kwargs["audio_bytes"] = item.payload["audio_bytes"]
            generation_kwargs["audio_mime_type"] = item.payload.get("audio_mime_type")
        reply: ConversationReply = self._gemini_chat.generate_structured(
            **generation_kwargs,  # type: ignore[arg-type]
        )
        if is_closing_response:
            reply = reply.model_copy(update={
                "interview_answer_complete": True,
                "interview_should_end": True,
            })
        elif is_interview and (
            int(item.payload.get("current_interview_answer_attempt_no", 1)) >= 2
            or bool(reply.interview_should_end)
        ):
            reply = reply.model_copy(update={"interview_answer_complete": True})
        return ConversationOutput(
            reply=reply,
            summary=summary,
            summarized_through_message_id=through_message_id,
            recent_message_start_sequence=recent_start_sequence,
        )

    def _emotion(self, item: ClaimedJob, suffix: str) -> EmotionAnalysis:
        return self._gemini_emotion.generate_structured(
            instructions=EMOTION_ANALYSIS_INSTRUCTIONS + suffix,
            input_text=str(item.payload["text"]),
            schema_name="emotion_analysis",
            result_type=EmotionAnalysis,
        )

    def _tts(self, item: ClaimedJob, _suffix: str) -> TTSOutput:
        return TTSOutput(
            wav=self._gemini_tts.synthesize(
                str(item.payload["text"]),
                str(item.payload.get("voice", "Kore")),
                str(item.payload.get("emotion", "neutral")),
                str(item.payload.get("voice_style", "")),
            ),
            storage_path=str(item.payload["storage_path"]),
        )

    def _feedback(self, item: ClaimedJob, suffix: str) -> GeneralFeedback:
        return self._openai_feedback.generate_structured(
            instructions=TURN_FEEDBACK_INSTRUCTIONS + suffix,
            input_text=json.dumps(item.payload, ensure_ascii=False, default=str),
            schema_name="turn_feedback",
            result_type=GeneralFeedback,
        )

    def _document_analysis(self, item: ClaimedJob, suffix: str) -> DocumentAnalysisOutput:
        analysis = self._openai_interview.generate_structured(
            instructions=DOCUMENT_ANALYSIS_INSTRUCTIONS + suffix,
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
                INTERVIEW_QUESTION_GENERATION_INSTRUCTIONS.format(
                    question_count=item.payload["question_count"],
                )
                + suffix
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
            instructions=SESSION_RESULT_INSTRUCTIONS + suffix,
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
