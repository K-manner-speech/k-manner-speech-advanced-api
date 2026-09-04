from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
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
from app.ai.rag import (
    EVIDENCE_SECTIONS,
    EvidenceChunk,
    assign_sections,
    chunk_document,
)
from app.ai.schemas import (
    ConversationReply,
    ConversationSummary,
    EmotionAnalysis,
    EvidenceRelevanceResult,
    GeneralFeedback,
    GeneralSessionResultOutput,
    InterviewEvaluation,
    InterviewSessionResultOutput,
    ScenarioGoalProgress,
)
from app.schemas.common import JobType
from worker.queue import ClaimedJob
from worker.tts_metrics import TTSMetrics

PCM_SAMPLE_RATE = 24_000
PCM_SAMPLE_WIDTH_BYTES = 2
PCM_STREAM_BATCH_SECONDS = 0.5
PCM_STREAM_BATCH_BYTES = int(
    PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH_BYTES * PCM_STREAM_BATCH_SECONDS
)
RAG_CANDIDATE_TOP_K = 15


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
    metrics: TTSMetrics


@dataclass(frozen=True, slots=True)
class FinalSessionOutput:
    result: GeneralSessionResultOutput | InterviewSessionResultOutput
    interview_evaluation: InterviewEvaluation | None


def relevance_score_gap(evidence: list[EvidenceChunk]) -> float | None:
    if len(evidence) < 2:
        return None
    return evidence[0].similarity - evidence[1].similarity


def filter_relevant_evidence(
    evidence: list[EvidenceChunk], result: EvidenceRelevanceResult
) -> list[EvidenceChunk]:
    by_id = {chunk.id: chunk for chunk in evidence}
    decision_ids = {item.chunk_id for item in result.decisions}
    if decision_ids != set(by_id):
        raise AIProviderError(
            "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
        )
    return [
        chunk
        for chunk in evidence
        if next(item for item in result.decisions if item.chunk_id == chunk.id).support_level
        != "unsupported"
    ]


class EvidenceRetriever(Protocol):
    def retrieve(
        self,
        *,
        user_id: UUID,
        document_versions: dict[UUID, int],
        query_embedding: list[float],
        threshold: float,
        top_k: int,
        sections: tuple[str, ...] | None = None,
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
        started = time.perf_counter()
        queue_wait_ms = 0.0
        if item.enqueued_at is not None:
            queue_wait_ms = max(
                0.0,
                (datetime.now(item.enqueued_at.tzinfo) - item.enqueued_at).total_seconds() * 1000,
            )
        input_text = str(item.payload["text"])
        raw_bundle = item.payload.get("prompt_bundle")
        bundle = raw_bundle if isinstance(raw_bundle, str) else None
        voice = self._prompt_composer.voice_for(bundle)
        instruction = self._prompt_composer.tts_instruction(
            bundle, str(item.payload.get("emotion", "neutral"))
        )
        stream_method = getattr(self._gemini_tts, "synthesize_stream", None)
        if self._tts_chunk_writer is not None and callable(stream_method):
            chunks: list[bytes] = []
            provider_first_chunk_ms: float | None = None
            db_write_ms = 0.0
            stream = cast(Callable[[str, str, str], Iterator[bytes]], stream_method)(
                input_text,
                voice.key if voice else "Kore",
                instruction,
            )

            def measured_stream() -> Iterator[bytes]:
                nonlocal provider_first_chunk_ms
                for provider_chunk in stream:
                    if provider_chunk and provider_first_chunk_ms is None:
                        provider_first_chunk_ms = (time.perf_counter() - started) * 1000
                    yield provider_chunk

            for sequence_no, chunk in enumerate(batch_pcm_chunks(measured_stream())):
                write_started = time.perf_counter()
                self._tts_chunk_writer(item, sequence_no, chunk)
                db_write_ms += (time.perf_counter() - write_started) * 1000
                chunks.append(chunk)
            if not chunks:
                raise AIProviderError("AI_PROVIDER_SCHEMA_INVALID", retryable=False)
            provider_total_ms = (time.perf_counter() - started) * 1000
            pcm = b"".join(chunks)
            wav = pcm_to_wav(
                pcm,
                sample_rate=PCM_SAMPLE_RATE,
                channels=1,
                sample_width=PCM_SAMPLE_WIDTH_BYTES,
            )
            audio_duration_ms = int(
                len(pcm) / (PCM_SAMPLE_RATE * PCM_SAMPLE_WIDTH_BYTES) * 1000
            )
        else:
            wav = self._gemini_tts.synthesize(
                input_text, voice.key if voice else "Kore", instruction
            )
            provider_total_ms = (time.perf_counter() - started) * 1000
            provider_first_chunk_ms = provider_total_ms
            db_write_ms = 0.0
            audio_duration_ms = max(0, int((len(wav) - 44) / 48_000 * 1000))
            chunks = [wav]
        return TTSOutput(
            wav=wav,
            storage_path=str(item.payload["storage_path"]),
            metrics=TTSMetrics(
                job_id=item.job_id,
                message_audio_id=item.target_id,
                text_chars=len(input_text),
                queue_wait_ms=queue_wait_ms,
                provider_first_chunk_ms=provider_first_chunk_ms,
                provider_total_ms=provider_total_ms,
                db_write_ms=db_write_ms,
                audio_duration_ms=audio_duration_ms,
                chunk_count=len(chunks),
                attempt_count=item.attempt_count,
                result="success",
            ),
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
        document_type = str(item.payload.get("document_type", "document"))
        chunks = chunk_document(
            str(item.payload["extracted_text"]),
            maximum_tokens=250,
            overlap_tokens=50,
            section=document_type,
        )
        # 방금 뽑은 섹션 문장을 청크와 같은 호출로 임베딩해, 각 청크가 문서의 어느
        # 부분인지 라벨을 붙인다. 질문 근거 검색을 경험·리스크로 좁히기 위해서다.
        section_sentences = [
            (name, sentence)
            for name, sentences in (
                ("summary", [analysis.sections.summary]),
                ("skills", analysis.sections.skills),
                ("experience", analysis.sections.experience),
                ("risks", analysis.sections.risks),
            )
            for sentence in sentences
            if sentence.strip()
        ]
        embeddings = self._embeddings.embed(
            [chunk.text for chunk in chunks] + [text for _, text in section_sentences]
        )
        chunk_embeddings = embeddings[: len(chunks)]
        sections = assign_sections(
            chunk_embeddings,
            [
                (name, embedding)
                for (name, _), embedding in zip(
                    section_sentences, embeddings[len(chunks) :], strict=True
                )
            ],
            fallback=document_type,
        )
        return DocumentAnalysisOutput(
            analysis=analysis,
            chunks=[
                (chunk.index, section, chunk.text, embedding)
                for chunk, section, embedding in zip(
                    chunks, sections, chunk_embeddings, strict=True
                )
            ],
        )

    def _configuration(self, item: ClaimedJob, suffix: str) -> ConfigurationOutput:
        # 검색어는 이력서 본문과 같은 문체의 서술문이어야 가까워진다. JSON 은 절반이
        # 키 이름과 기호이고, language·difficulty 는 질문을 만들 때의 조건이지
        # 이력서에서 찾을 내용이 아니라 검색을 흐린다. 조건은 아래 프롬프트에만 넘긴다.
        role = str(item.payload.get("desired_role") or "").strip()
        query = (
            f"{role} 지원자의 " if role else ""
        ) + "실무 프로젝트 경험, 문제 해결 과정, 성능 개선과 기술 선택 근거"
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
            top_k=RAG_CANDIDATE_TOP_K,
            sections=EVIDENCE_SECTIONS,
        )
        if not evidence:
            # 라벨이 붙기 전에 분석된 문서는 섹션 필터에 하나도 걸리지 않는다.
            # 재분석을 요구하는 대신 문서 전체에서 다시 찾는다.
            evidence = self._evidence_retriever.retrieve(
                user_id=item.user_id,
                document_versions=versions,
                query_embedding=query_embedding,
                threshold=self._rag_threshold,
                top_k=RAG_CANDIDATE_TOP_K,
            )
        if not evidence:
            raise AIProviderError("INSUFFICIENT_EVIDENCE", retryable=False)
        relevance = self._openai_interview.generate_structured(
            instructions=(
                self._prompt_composer.task_instruction("interview_evidence_relevance")
                + suffix
            ),
            input_text=json.dumps(
                {
                    "conditions": item.payload["conditions"],
                    "desired_role": item.payload.get("desired_role"),
                    "top_similarity": evidence[0].similarity,
                    "top1_top2_gap": relevance_score_gap(evidence),
                    "evidence": [
                        {
                            "chunk_id": str(chunk.id),
                            "section": chunk.section,
                            "text": chunk.text,
                            "similarity": chunk.similarity,
                        }
                        for chunk in evidence
                    ],
                },
                ensure_ascii=False,
            ),
            schema_name="interview_evidence_relevance",
            result_type=EvidenceRelevanceResult,
        )
        evidence = filter_relevant_evidence(evidence, relevance)
        if not evidence:
            raise AIProviderError("INSUFFICIENT_EVIDENCE", retryable=False)
        relevance_by_id = {item.chunk_id: item for item in relevance.decisions}
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
                            "support_level": relevance_by_id[chunk.id].support_level,
                            "supported_claims": relevance_by_id[chunk.id].supported_claims,
                            "unsupported_claims": relevance_by_id[
                                chunk.id
                            ].unsupported_claims,
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
