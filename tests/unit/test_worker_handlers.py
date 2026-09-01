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
    def __init__(self, reply: ConversationReply | None = None) -> None:
        self.count_calls = 0
        self.generate_calls = 0
        self.reply = reply or ConversationReply(
            reply="반갑습니다.", persona_emotion="neutral", summary=None
        )

    def count_tokens(self, _text: str) -> int:
        self.count_calls += 1
        return 1

    def generate_structured(self, **_kwargs: object) -> ConversationReply:
        self.generate_calls += 1
        return self.reply


def _conversation_executors(provider: _ConversationProvider) -> WorkerExecutors:
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


def _interview_item(
    *,
    next_question: dict[str, str] | None,
    answer_attempt_no: int = 1,
    answer_limit_reached: bool = False,
    answer_text: str = "답변",
) -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(),
        job_type=JobType.CONVERSATION_TEXT,
        user_id=uuid4(),
        target_id=uuid4(),
        processing_token=uuid4(),
        attempt_count=1,
        schema_repair_count=0,
        deadline_at=datetime.now(UTC),
        payload={
            "room": {"practice_type": "interview"},
            "messages": [{"id": str(uuid4()), "sequence_no": 1, "content": answer_text}],
            "current_interview_question": {"id": str(uuid4()), "text": "마지막 질문"},
            "current_interview_answer_attempt_no": answer_attempt_no,
            "next_interview_question": next_question,
            "interview_answer_limit_reached": answer_limit_reached,
        },
    )


def test_final_completed_interview_answer_forces_end_without_ending_early() -> None:
    completed = ConversationReply(
        reply="답변 감사합니다.",
        persona_emotion="neutral",
        summary=None,
        interview_answer_complete=True,
        interview_should_end=False,
    )

    final_output = _conversation_executors(_ConversationProvider(completed)).execute(
        _interview_item(next_question=None)
    )
    assert final_output.reply.interview_should_end is True, "FINAL-INTERVIEW-END-FORCED"
    assert final_output.reply.interview_answer_complete is True
    assert (
        final_output.reply.reply
        == "답변 감사합니다. 준비된 질문은 모두 마쳤습니다. 오늘 면접 수고하셨습니다."
    )

    next_output = _conversation_executors(_ConversationProvider(completed)).execute(
        _interview_item(next_question={"id": str(uuid4()), "text": "다음 질문"})
    )
    assert next_output.reply.interview_should_end is False
    assert next_output.reply.reply == "네, 답변 잘 들었습니다. 다음 질문"

    incomplete = completed.model_copy(update={"interview_answer_complete": False})
    incomplete_output = _conversation_executors(_ConversationProvider(incomplete)).execute(
        _interview_item(next_question=None)
    )
    assert incomplete_output.reply.interview_should_end is False

    ai_end_mistake = completed.model_copy(update={"interview_should_end": True})
    explicit_end_output = _conversation_executors(_ConversationProvider(ai_end_mistake)).execute(
        _interview_item(next_question={"id": str(uuid4()), "text": "다음 질문"})
    )
    assert explicit_end_output.reply.interview_should_end is False
    assert explicit_end_output.reply.reply == "네, 답변 잘 들었습니다. 다음 질문"


def test_incomplete_first_answer_keeps_ai_generated_followup() -> None:
    provider_reply = ConversationReply(
        reply="그 기술을 선택한 구체적인 이유도 설명해 주시겠어요?",
        persona_emotion="curious",
        summary=None,
        interview_answer_complete=False,
        interview_should_end=False,
    )

    output = _conversation_executors(_ConversationProvider(provider_reply)).execute(
        _interview_item(next_question={"id": str(uuid4()), "text": "다음 질문"})
    )

    assert output.reply.reply == "그 기술을 선택한 구체적인 이유도 설명해 주시겠어요?"
    assert output.reply.interview_answer_complete is False
    assert output.reply.interview_should_end is False


def test_coaching_style_followup_is_replaced_with_neutral_probe() -> None:
    coaching = ConversationReply(
        reply=(
            "JSON 스키마를 미리 정의하고 누락 필드는 기본값으로 채우는 방식을 "
            "고민해 보시는 건 어떨까요?"
        ),
        persona_emotion="curious",
        summary=None,
        interview_answer_complete=False,
        interview_should_end=False,
    )

    output = _conversation_executors(_ConversationProvider(coaching)).execute(
        _interview_item(next_question={"id": str(uuid4()), "text": "다음 질문"})
    )

    assert output.reply.reply == (
        "현재 답변에서 말씀하신 내용을 질문과 연결해, "
        "구체적인 이유와 처리 과정을 설명해 주시겠어요?"
    )
    assert output.reply.interview_answer_complete is False


def test_unearned_praise_before_followup_is_replaced_with_neutral_probe() -> None:
    praising = ConversationReply(
        reply=(
            "네, 잘 개선하셨군요. 그렇다면 구체적인 구현 과정을 "
            "설명해 주시겠어요?"
        ),
        persona_emotion="happy",
        summary=None,
        interview_answer_complete=False,
        interview_should_end=False,
    )

    output = _conversation_executors(_ConversationProvider(praising)).execute(
        _interview_item(next_question={"id": str(uuid4()), "text": "다음 질문"})
    )

    assert output.reply.reply == (
        "현재 답변에서 말씀하신 내용을 질문과 연결해, "
        "구체적인 이유와 처리 과정을 설명해 주시겠어요?"
    )


def test_incomplete_second_answer_uses_fixed_final_confirmation() -> None:
    provider_reply = ConversationReply(
        reply="다시 보충해 주시겠어요?",
        persona_emotion="curious",
        summary=None,
        interview_answer_complete=False,
        interview_should_end=False,
    )

    output = _conversation_executors(_ConversationProvider(provider_reply)).execute(
        _interview_item(
            next_question={"id": str(uuid4()), "text": "다음 질문"},
            answer_attempt_no=2,
        )
    )

    assert output.reply.interview_answer_complete is False
    assert output.reply.reply == (
        "네, 말씀해 주신 내용 확인했습니다. "
        "이 질문에 대해 더 보충하실 내용이 있으신가요?"
    )


def test_explicit_second_non_answer_overrides_ai_complete_decision() -> None:
    mistaken_complete = ConversationReply(
        reply="다음 질문으로 넘어가겠습니다.",
        persona_emotion="neutral",
        summary=None,
        interview_answer_complete=True,
        interview_should_end=False,
    )

    output = _conversation_executors(_ConversationProvider(mistaken_complete)).execute(
        _interview_item(
            next_question={"id": str(uuid4()), "text": "다음 질문"},
            answer_attempt_no=2,
            answer_text="그건 잘 모르겠습니다.",
        )
    )

    assert output.reply.interview_answer_complete is False
    assert output.reply.reply == (
        "네, 말씀해 주신 내용 확인했습니다. "
        "이 질문에 대해 더 보충하실 내용이 있으신가요?"
    )


def test_third_answer_forces_next_question_with_fixed_transition() -> None:
    provider_reply = ConversationReply(
        reply="한 번 더 설명해 주세요.",
        persona_emotion="curious",
        summary=None,
        interview_answer_complete=False,
        interview_should_end=False,
    )

    output = _conversation_executors(_ConversationProvider(provider_reply)).execute(
        _interview_item(
            next_question={"id": str(uuid4()), "text": "다음 질문입니다."},
            answer_attempt_no=3,
        )
    )

    assert output.reply.reply == "네, 답변 잘 들었습니다. 다음 질문입니다."
    assert output.reply.interview_answer_complete is True
    assert output.reply.interview_should_end is False


def test_third_answer_on_final_question_forces_fixed_closing() -> None:
    provider_reply = ConversationReply(
        reply="추가 질문입니다.",
        persona_emotion="curious",
        summary=None,
        interview_answer_complete=False,
        interview_should_end=False,
    )

    output = _conversation_executors(_ConversationProvider(provider_reply)).execute(
        _interview_item(next_question=None, answer_attempt_no=3)
    )

    assert output.reply.reply == (
        "답변 감사합니다. 준비된 질문은 모두 마쳤습니다. 오늘 면접 수고하셨습니다."
    )
    assert output.reply.interview_answer_complete is True
    assert output.reply.interview_should_end is True


def test_interview_answer_limit_forces_fixed_end() -> None:
    provider_reply = ConversationReply(
        reply="새로운 질문입니다.",
        persona_emotion="curious",
        summary=None,
        interview_answer_complete=False,
        interview_should_end=False,
    )

    output = _conversation_executors(_ConversationProvider(provider_reply)).execute(
        _interview_item(
            next_question={"id": str(uuid4()), "text": "다음 질문"},
            answer_limit_reached=True,
        )
    )

    assert output.reply.reply == (
        "답변 감사합니다. 준비된 질문은 모두 마쳤습니다. 오늘 면접 수고하셨습니다."
    )
    assert output.reply.interview_answer_complete is True
    assert output.reply.interview_should_end is True


def test_first_conversation_skips_remote_token_count_before_reply_generation() -> None:
    provider = _ConversationProvider()
    executors = _conversation_executors(provider)
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
