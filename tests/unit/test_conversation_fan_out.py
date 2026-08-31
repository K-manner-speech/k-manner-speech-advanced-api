from __future__ import annotations

import inspect
import re

from worker.domain_adapters import ConversationAdapter


def test_conversation_fan_out_enqueues_tts_before_feedback_without_emotion_job() -> None:
    source = inspect.getsource(ConversationAdapter._fan_out)
    enqueued_job_types = re.findall(r"job_type=JobType\.(\w+)", source)

    assert "message_emotion_analysis" not in source
    assert enqueued_job_types == ["TTS_GENERATION", "TURN_FEEDBACK"]
