from __future__ import annotations

import inspect
import re

from worker.domain_adapters import ConversationAdapter


def test_conversation_fan_out_enqueues_tts_before_feedback_without_emotion_job() -> None:
    source = inspect.getsource(ConversationAdapter._fan_out)
    enqueued_job_types = re.findall(r"job_type=JobType\.(\w+)", source)

    assert "message_emotion_analysis" not in source
    assert enqueued_job_types == ["TTS_GENERATION", "TURN_FEEDBACK"]


def test_interview_fan_out_skips_turn_feedback_but_keeps_tts() -> None:
    source = inspect.getsource(ConversationAdapter._fan_out)
    complete_source = inspect.getsource(ConversationAdapter.complete)

    assert "practice_type" in source
    assert "practice_type != \"interview\"" in source
    assert "job_type=JobType.TTS_GENERATION" in source
    assert "target[\"practice_type\"]" in complete_source
