from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
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
from app.ai.prompts.composer import PromptComposer
from app.ai.prompts.policies.conversation import (
    CONVERSATION_SUMMARY_INSTRUCTIONS,
    INTERVIEW_CLOSING_REPLY,
    INTERVIEW_CONFIRMATION_REPLY,
    INTERVIEW_NEUTRAL_FOLLOWUP_REPLY,
    INTERVIEW_NEXT_QUESTION_PREFIX,
    build_conversation_instructions,
)
from app.ai.providers.gemini import pcm_to_wav
from app.ai.rag import EvidenceChunk, chunk_document
from app.ai.schemas import (
    ConversationReply,
    ConversationSummary,
    EmotionAnalysis,
    GeneralFeedback,
    GeneralSessionResultOutput,
    InterviewEvaluation,
    InterviewSessionResultOutput,
    ScenarioGoalProgress,
)
from app.schemas.common import JobType
from worker.queue import ClaimedJob

PCM_SAMPLE_RATE = 24_000
PCM_SAMPLE_WIDTH_BYTES = 2
PCM_STREAM_BATCH_SECONDS = 0.5
PCM_STREAM_BATCH_BYTES = int(
    PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH_BYTES * PCM_STREAM_BATCH_SECONDS
)


def batch_pcm_chunks(
    chunks: Iterable[bytes], batch_bytes: int = PCM_STREAM_BATCH_BYTES
) -> Iterator[bytes]:
    """Coalesce provider deltas into DB-sized PCM batches without altering audio."""
    if batch_bytes <= 0:
        raise ValueError("batch_bytes must be positive")
    buffered = bytearray()
    for chunk in chunks:
        if not chunk:
            continue
        buffered.extend(chunk)
        while len(buffered) >= batch_bytes:
            yield bytes(buffered[:batch_bytes])
            del buffered[:batch_bytes]
    if buffered:
        yield bytes(buffered)


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
    result: GeneralSessionResultOutput | InterviewSessionResultOutput
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
        prompt_composer: PromptComposer | None = None,
        tts_chunk_writer: Callable[[ClaimedJob, int, bytes], None] | None = None,
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
        self._prompt_composer = prompt_composer or PromptComposer.default()
        self._tts_chunk_writer = tts_chunk_writer

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
            JobType.SCENARIO_GOAL_PROGRESS: self._goal_progress,
        }
        return handlers[item.job_type](item, instructions_suffix)

    def _conversation(self, item: ClaimedJob, suffix: str) -> ConversationOutput:
        is_interview = item.payload.get("room", {}).get("practice_type") == "interview"
        model_payload = item.payload
        if is_interview:
            model_payload = {
                key: value
                for key, value in item.payload.items()
                if key != "next_interview_question"
            }
        input_text = json.dumps(model_payload, ensure_ascii=False, default=str)
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
                    **model_payload,
                    "context_summary": summary.model_dump(),
                    "messages": recent,
                }
                input_text = json.dumps(compact_payload, ensure_ascii=False, default=str)
        is_closing_response = bool(item.payload.get("interview_closing_response"))
        room_payload = item.payload.get("room")
        persona_bundle = None
        if isinstance(room_payload, dict):
            persona_payload = room_payload.get("persona")
            if isinstance(persona_payload, dict):
                raw_bundle = persona_payload.get("prompt_bundle")
                if isinstance(raw_bundle, str) and raw_bundle:
                    persona_bundle = raw_bundle
        role = room_payload.get("role") if isinstance(room_payload, dict) else None
        catalog_prompt = self._prompt_composer.compose_conversation(
            persona_bundle, role if isinstance(role, str) else None
        )
        generation_kwargs: dict[str, object] = {
            "instructions": build_conversation_instructions(
                is_interview=is_interview,
                is_closing_response=is_closing_response,
                is_scenario=room_payload.get("practice_type") == "scenario"
                if isinstance(room_payload, dict)
                else False,
                catalog_prompt=catalog_prompt,
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
        if is_closing_response or bool(item.payload.get("interview_answer_limit_reached")):
            reply = reply.model_copy(update={
                "reply": INTERVIEW_CLOSING_REPLY,
                "interview_answer_complete": True,
                "interview_should_end": True,
            })
        elif is_interview:
            reply = reply.model_copy(update={"interview_should_end": False})
            answer_attempt_no = int(
                item.payload.get("current_interview_answer_attempt_no", 1)
            )
            next_question = item.payload.get("next_interview_question")
            latest_answer = str(messages[-1].get("content", "")).strip() if messages else ""
            explicit_non_answer_markers = (
                "모르겠습니다",
                "잘 모르",
                "모르겠",
                "없습니다",
                "딱히 없",
                "기억나지",
                "생각나지",
            )
            is_explicit_non_answer = (
                answer_attempt_no <= 2
                and len(latest_answer) <= 40
                and any(marker in latest_answer for marker in explicit_non_answer_markers)
            )
            if is_explicit_non_answer:
                reply = reply.model_copy(update={"interview_answer_complete": False})
            if answer_attempt_no >= 3:
                reply = reply.model_copy(update={"interview_answer_complete": True})
            if bool(reply.interview_answer_complete):
                if next_question is None:
                    reply = reply.model_copy(update={
                        "reply": INTERVIEW_CLOSING_REPLY,
                        "interview_answer_complete": True,
                        "interview_should_end": True,
                    })
                elif isinstance(next_question, dict):
                    next_question_text = str(next_question.get("text", "")).strip()
                    reply = reply.model_copy(update={
                        "reply": (
                            f"{INTERVIEW_NEXT_QUESTION_PREFIX} {next_question_text}"
                        ).strip(),
                        "interview_answer_complete": True,
                        "interview_should_end": False,
                    })
            elif answer_attempt_no >= 2:
                reply = reply.model_copy(update={
                    "reply": INTERVIEW_CONFIRMATION_REPLY,
                    "interview_answer_complete": False,
                    "interview_should_end": False,
                })
            else:
                coaching_markers = (
                    "고민해 보시는",
                    "어떨까요",
                    "권장",
                    "추천",
                    "제안",
                    "하는 것이 좋",
                    "해 보세요",
                    "하셨군요",
                )
                if any(marker in reply.reply for marker in coaching_markers):
                    reply = reply.model_copy(update={
                        "reply": INTERVIEW_NEUTRAL_FOLLOWUP_REPLY,
                        "interview_answer_complete": False,
                        "interview_should_end": False,
                    })
                reply = reply.model_copy(update={
                    "interview_answer_complete": False,
                    "interview_should_end": False,
                })
        return ConversationOutput(
            reply=reply,
            summary=summary,
            summarized_through_message_id=through_message_id,
            recent_message_start_sequence=recent_start_sequence,
        )

    def _emotion(self, item: ClaimedJob, suffix: str) -> EmotionAnalysis:
        return self._gemini_emotion.generate_structured(
            instructions=self._prompt_composer.task_instruction("emotion_analysis") + suffix,
            input_text=str(item.payload["text"]),
            schema_name="emotion_analysis",
            result_type=EmotionAnalysis,
        )

    def _tts(self, item: ClaimedJob, _suffix: str) -> TTSOutput:
        raw_bundle = item.payload.get("prompt_bundle")
        bundle = raw_bundle if isinstance(raw_bundle, str) else None
        voice = self._prompt_composer.voice_for(bundle)
        instruction = self._prompt_composer.tts_instruction(
            bundle, str(item.payload.get("emotion", "neutral"))
        )
        stream_method = getattr(self._gemini_tts, "synthesize_stream", None)
        if self._tts_chunk_writer is not None and callable(stream_method):
            chunks: list[bytes] = []
            stream = cast(Callable[[str, str, str], Iterator[bytes]], stream_method)(
                str(item.payload["text"]),
                voice.key if voice else "Kore",
                instruction,
            )
            for sequence_no, chunk in enumerate(batch_pcm_chunks(stream)):
                self._tts_chunk_writer(item, sequence_no, chunk)
                chunks.append(chunk)
            if not chunks:
                raise AIProviderError("AI_PROVIDER_SCHEMA_INVALID", retryable=False)
            wav = pcm_to_wav(
                b"".join(chunks),
                sample_rate=PCM_SAMPLE_RATE,
                channels=1,
                sample_width=PCM_SAMPLE_WIDTH_BYTES,
            )
        else:
            wav = self._gemini_tts.synthesize(
                str(item.payload["text"]), voice.key if voice else "Kore", instruction
            )
        return TTSOutput(
            wav=wav,
            storage_path=str(item.payload["storage_path"]),
        )

    def _feedback(self, item: ClaimedJob, suffix: str) -> GeneralFeedback:
        return self._openai_feedback.generate_structured(
            instructions=self._prompt_composer.task_instruction("turn_feedback") + suffix,
            input_text=json.dumps(item.payload, ensure_ascii=False, default=str),
            schema_name="turn_feedback",
            result_type=GeneralFeedback,
        )

    def _goal_progress(self, item: ClaimedJob, suffix: str) -> ScenarioGoalProgress:
        return self._openai_feedback.generate_structured(
            instructions=self._prompt_composer.task_instruction("scenario_goal_progress") + suffix,
            input_text=json.dumps(item.payload, ensure_ascii=False, default=str),
            schema_name="scenario_goal_progress",
            result_type=ScenarioGoalProgress,
        )

    def _document_analysis(self, item: ClaimedJob, suffix: str) -> DocumentAnalysisOutput:
        analysis = self._openai_interview.generate_structured(
            instructions=self._prompt_composer.task_instruction("document_analysis") + suffix,
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
                self._prompt_composer.task_instruction(
                    "interview_question_generation"
                ).format(question_count=item.payload["question_count"])
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
        practice_type = item.payload.get("practice_type")
        if practice_type == "interview":
            task_name = "session_result_interview"
            result_type: type[GeneralSessionResultOutput] | type[
                InterviewSessionResultOutput
            ] = InterviewSessionResultOutput
        elif practice_type == "scenario":
            task_name = "session_result_scenario"
            result_type = GeneralSessionResultOutput
        elif practice_type == "free_chat":
            task_name = "session_result_free_chat"
            result_type = GeneralSessionResultOutput
        else:
            raise AIProviderError(
                "AI_PROVIDER_SCHEMA_INVALID",
                retryable=False,
                schema_invalid=True,
            )
        generated = self._openai_interview.generate_structured(
            instructions=self._prompt_composer.task_instruction(task_name) + suffix,
            input_text=json.dumps(item.payload, ensure_ascii=False, default=str),
            schema_name=task_name,
            result_type=result_type,
        )
        evaluation = None
        if isinstance(generated, InterviewSessionResultOutput):
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
