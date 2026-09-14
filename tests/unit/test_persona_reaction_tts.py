from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
from unittest.mock import MagicMock
from uuid import uuid4
from wave import open as open_wave

from app.ai.providers.gemini import GeminiSpeechClient
from app.repositories.conversation import ConversationRepository
from app.schemas.common import JobType
from worker.domain_adapters import INTERVIEWER_PROMPT_BUNDLE, TTSAdapter
from worker.executors import TTSOutput, WorkerExecutors
from worker.queue import ClaimedJob


class RecordingSpeechProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def synthesize(self, text: str, voice: str, delivery_instruction: str) -> bytes:
        self.calls.append((text, voice, delivery_instruction))
        return b"wav"


class StreamingSpeechProvider(RecordingSpeechProvider):
    def synthesize_stream(self, text: str, voice: str, delivery_instruction: str):
        self.calls.append((text, voice, delivery_instruction))
        yield b"\x00\x00"
        yield b"\x01\x00"


def tts_item(emotion: str) -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(),
        job_type=JobType.TTS_GENERATION,
        user_id=uuid4(),
        target_id=uuid4(),
        processing_token=uuid4(),
        attempt_count=1,
        schema_repair_count=0,
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        payload={
            "text": "괜찮습니다.",
            "voice": "Kore",
            "emotion": emotion,
            "storage_path": "a.wav",
        },
    )


def test_tts_executor_passes_persona_reaction_to_speech_provider() -> None:
    speech = RecordingSpeechProvider()
    dependency = MagicMock()
    executors = WorkerExecutors(
        gemini_chat=dependency,
        token_counter=dependency,
        gemini_emotion=dependency,
        gemini_tts=speech,
        openai_feedback=dependency,
        openai_interview=dependency,
        embeddings=dependency,
        evidence_retriever=dependency,
        rag_threshold=0.7,
        context_summary_trigger_tokens=4_000,
    )

    executors.execute(tts_item("embarrassment"))

    assert len(speech.calls) == 1
    text, voice, instruction = speech.calls[0]
    assert (text, voice) == ("괜찮습니다.", "Kore")
    # 감정별 어조는 catalog/emotions 조각에서 온다.
    assert "난처한" in instruction


def test_tts_executor_publishes_ordered_pcm_chunks_and_builds_final_wav() -> None:
    speech = StreamingSpeechProvider()
    dependency = MagicMock()
    published: list[tuple[int, bytes]] = []
    executors = WorkerExecutors(
        gemini_chat=dependency,
        token_counter=dependency,
        gemini_emotion=dependency,
        gemini_tts=speech,
        openai_feedback=dependency,
        openai_interview=dependency,
        embeddings=dependency,
        evidence_retriever=dependency,
        rag_threshold=0.7,
        context_summary_trigger_tokens=4_000,
        tts_chunk_writer=lambda _item, sequence, chunk: published.append((sequence, chunk)),
    )

    output = executors.execute(tts_item("happy"))

    assert isinstance(output, TTSOutput)
    assert published == [(0, b"\x00\x00\x01\x00")]
    with open_wave(BytesIO(output.wav), "rb") as audio:
        assert audio.readframes(2) == b"\x00\x00\x01\x00"


def _tts_claim(prompt_bundle_key: str | None, practice_type: str = "free_chat") -> object:
    session = MagicMock()
    session.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "id": uuid4(),
        "processing_token": uuid4(),
        "storage_path": "owner/room/message.wav",
        "content": "알겠습니다.",
        "persona_emotion": "curious",
        "prompt_bundle_key": prompt_bundle_key,
        "practice_type": practice_type,
    }
    claim = TTSAdapter(MagicMock()).claim(
        session,
        {"message_audio_id": uuid4(), "user_id": uuid4()},
    )
    return claim, session


def test_tts_claim_reads_persisted_persona_reaction() -> None:
    claim, session = _tts_claim(None)

    assert claim is not None
    assert claim.payload["emotion"] == "curious"
    assert "m.persona_emotion" in str(session.execute.call_args.args[0])


def test_tts_claim_omits_the_bundle_when_the_persona_has_none() -> None:
    claim, _ = _tts_claim(None)

    assert claim is not None
    assert "prompt_bundle" not in claim.payload


def test_tts_claim_gives_the_interviewer_a_voice() -> None:
    """면접방에는 personas 행이 없어 번들이 빈다.

    그대로 두면 TTS 가 기본 음성으로 떨어져 면접관이 매번 다른 사람처럼
    들린다. 전용 페르소나가 생기기 전까지 김민준 팀장의 번들을 빌려 쓴다.
    """
    claim, session = _tts_claim(None, practice_type="interview")

    assert claim is not None
    assert claim.payload["prompt_bundle"] == INTERVIEWER_PROMPT_BUNDLE
    assert "r.practice_type" in str(session.execute.call_args.args[0])


def test_tts_claim_carries_the_personas_prompt_bundle() -> None:
    claim, session = _tts_claim("seojun")

    assert claim is not None
    assert claim.payload["prompt_bundle"] == "seojun"
    assert "p.prompt_bundle_key" in str(session.execute.call_args.args[0])


def test_message_list_query_exposes_persona_reaction_as_emotion_snapshot() -> None:
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = uuid4()
    session.execute.return_value.mappings.return_value.__iter__.return_value = iter([])

    ConversationRepository(session).list_messages(uuid4(), uuid4(), 20)

    message_query = str(session.execute.call_args.args[0])
    assert "m.persona_emotion" in message_query
    assert "as emotion_label" in message_query


def test_gemini_speech_forwards_the_delivery_instruction(monkeypatch: MagicMock) -> None:
    captured: dict[str, object] = {}

    def fake_post_json(
        _endpoint: str,
        payload: dict[str, object],
        *_args: object,
        **_kwargs: object,
    ) -> dict[str, object]:
        captured.update(payload)
        return {"type": "audio", "data": base64.b64encode(b"\x00\x00").decode()}

    monkeypatch.setattr("app.ai.providers.gemini.post_json", fake_post_json)

    GeminiSpeechClient("secret", "tts-model").synthesize(
        "괜찮습니다.", "Kore", "낮고 부드러우며 아쉬움이 느껴지는 어조로 말하세요."
    )

    assert "아쉬움" in str(captured["input"])
    assert "괜찮습니다." in str(captured["input"])
