from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.ai.schemas import ConversationReply
from app.schemas.common import JobType
from worker.executors import WorkerExecutors
from worker.queue import ClaimedJob


class RecordingChat:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def count_tokens(self, text: str) -> int:
        return 1

    def generate_structured(self, **kwargs: Any) -> ConversationReply:
        self.calls.append(kwargs)
        return ConversationReply(
            reply="그 말씀을 들으니 걱정되네요.", persona_emotion="sad", summary=None,
            interview_answer_complete=False,
        )


def test_voice_conversation_sends_original_audio_with_persona_viewpoint_prompt() -> None:
    chat = RecordingChat()
    dependency = RecordingChat()
    executor = WorkerExecutors(
        gemini_chat=chat,
        token_counter=chat,
        gemini_emotion=dependency,
        gemini_tts=dependency,  # type: ignore[arg-type]
        openai_feedback=dependency,
        openai_interview=dependency,
        embeddings=dependency,  # type: ignore[arg-type]
        evidence_retriever=dependency,  # type: ignore[arg-type]
        rag_threshold=0.7,
        context_summary_trigger_tokens=4_000,
    )
    item = ClaimedJob(
        job_id=uuid4(), job_type=JobType.CONVERSATION_TEXT, user_id=uuid4(),
        target_id=uuid4(), processing_token=uuid4(), attempt_count=1,
        schema_repair_count=0, deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        payload={
            "messages": [{"id": str(uuid4()), "sender_type": "user", "content": "괜찮아요"}],
            "audio_bytes": b"original-audio",
            "audio_mime_type": "audio/webm",
        },
    )

    executor.execute(item)

    call = chat.calls[-1]
    assert "사용자 말을 들은 페르소나의 입장" in call["instructions"]
    assert call["audio_bytes"] == b"original-audio"
    assert call["audio_mime_type"] == "audio/webm"


def test_interview_prompt_requires_semantic_completion_before_next_question() -> None:
    chat = RecordingChat()
    dependency = RecordingChat()
    executor = WorkerExecutors(
        gemini_chat=chat, token_counter=chat, gemini_emotion=dependency,
        gemini_tts=dependency, openai_feedback=dependency,
        openai_interview=dependency, embeddings=dependency,
        evidence_retriever=dependency, rag_threshold=0.7,
        context_summary_trigger_tokens=4_000,
    )
    item = ClaimedJob(
        job_id=uuid4(), job_type=JobType.CONVERSATION_TEXT, user_id=uuid4(),
        target_id=uuid4(), processing_token=uuid4(), attempt_count=1,
        schema_repair_count=0, deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        payload={
            "room": {"practice_type": "interview"},
            "messages": [{"id": str(uuid4()), "sender_type": "user", "content": "일부 답변"}],
            "current_interview_question": {"id": str(uuid4()), "text": "지원 동기는?"},
            "next_interview_question": {"id": str(uuid4()), "text": "강점은?"},
            "current_interview_answer_attempt_no": 2,
        },
    )

    result = executor.execute(item)

    instructions = chat.calls[-1]["instructions"]
    assert "완전히 답했는지" in instructions
    assert "질문 목록" in instructions
    assert "품질이나 정답 여부" in instructions
    assert "추가 질문은 최대 한 번" in instructions
    assert "종료 의사" in instructions
    assert "더 말씀하실 내용이 있는지" in instructions
    assert "모른다고 답한 첫 답변을 바로 완료 처리하지 마세요" in instructions
    assert result.reply.interview_answer_complete is True


def test_interview_closing_response_ends_after_final_remarks() -> None:
    chat = RecordingChat()
    dependency = RecordingChat()
    executor = WorkerExecutors(
        gemini_chat=chat, token_counter=chat, gemini_emotion=dependency,
        gemini_tts=dependency, openai_feedback=dependency,
        openai_interview=dependency, embeddings=dependency,
        evidence_retriever=dependency, rag_threshold=0.7,
        context_summary_trigger_tokens=4_000,
    )
    item = ClaimedJob(
        job_id=uuid4(), job_type=JobType.CONVERSATION_TEXT, user_id=uuid4(),
        target_id=uuid4(), processing_token=uuid4(), attempt_count=1,
        schema_repair_count=0, deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        payload={"room": {"practice_type": "interview"}, "messages": [],
                 "interview_closing_response": True},
    )

    result = executor.execute(item)

    assert "면접 종료 멘트" in chat.calls[-1]["instructions"]
    assert result.reply.interview_should_end is True
