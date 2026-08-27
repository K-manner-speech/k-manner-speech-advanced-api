from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.adapters.interview_provider import (
    GeneratedQuestion,
    InterviewQuestionResult,
    QuestionSourceRef,
)
from app.ai.interfaces import AIProviderError
from app.ai.rag import EvidenceChunk
from app.ai.schemas import ConversationReply
from app.schemas.common import JobType
from worker.executors import (
    WorkerExecutors,
    split_conversation_messages,
    validate_question_evidence,
)
from worker.queue import ClaimedJob


def test_interview_question_source_refs_must_match_retrieved_evidence() -> None:
    owner_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    evidence = [
        EvidenceChunk(
            id=chunk_id,
            user_id=owner_id,
            document_id=document_id,
            document_version=1,
            text="검증된 경력 근거",
            section="resume",
            similarity=0.91,
        )
    ]
    questions = InterviewQuestionResult(
        questions=[
            GeneratedQuestion(
                sequence=1,
                text="이 경험을 설명해 주세요.",
                type="experience",
                required=True,
                source_refs=[
                    QuestionSourceRef(
                        section="resume",
                        chunk_id=uuid4(),
                        document_id=document_id,
                        evidence=None,
                    )
                ],
                evaluation_focus=["specificity"],
            )
        ]
    )

    try:
        validate_question_evidence(questions, evidence)
    except AIProviderError as error:
        assert error.schema_invalid is True
        assert error.retryable is False
    else:
        raise AssertionError("fabricated RAG source reference must be rejected")


def test_context_rollup_preserves_latest_ai_and_user_messages_raw() -> None:
    messages = [
        {"id": str(uuid4()), "sequence_no": index, "content": f"m{index}"}
        for index in range(1, 6)
    ]

    older, recent = split_conversation_messages(messages)

    assert [item["sequence_no"] for item in older] == [1, 2, 3]
    assert [item["sequence_no"] for item in recent] == [4, 5]


class _ConversationProvider:
    def __init__(self) -> None:
        self.count_calls = 0
        self.generate_calls = 0

    def count_tokens(self, _text: str) -> int:
        self.count_calls += 1
        return 1

    def generate_structured(self, **_kwargs: object) -> ConversationReply:
        self.generate_calls += 1
        return ConversationReply(reply="반갑습니다.", persona_emotion="neutral", summary=None)


def test_first_conversation_skips_remote_token_count_before_reply_generation() -> None:
    provider = _ConversationProvider()
    executors = WorkerExecutors(
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
    item = ClaimedJob(
        job_id=uuid4(),
        job_type=JobType.CONVERSATION_TEXT,
        user_id=uuid4(),
        target_id=uuid4(),
        processing_token=uuid4(),
        attempt_count=1,
        schema_repair_count=0,
        deadline_at=datetime.now(UTC),
        payload={"messages": [{"id": str(uuid4()), "sequence_no": 1, "content": "안녕하세요"}]},
    )

    output = executors.execute(item)

    assert output.reply.reply == "반갑습니다."
    assert provider.count_calls == 0
    assert provider.generate_calls == 1
