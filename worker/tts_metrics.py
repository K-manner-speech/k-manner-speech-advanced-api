from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def _milliseconds(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, value), 1)


@dataclass(slots=True)
class TTSMetrics:
    job_id: UUID
    message_audio_id: UUID
    text_chars: int
    queue_wait_ms: float
    attempt_count: int
    result: str
    provider_first_chunk_ms: float | None = None
    provider_total_ms: float | None = None
    db_write_ms: float | None = None
    storage_upload_ms: float | None = None
    end_to_end_ms: float | None = None
    audio_duration_ms: int | None = None
    chunk_count: int = 0
    error_code: str | None = None

    @classmethod
    def failure(
        cls, *, job_id: UUID, message_audio_id: UUID, text_chars: int,
        queue_wait_ms: float, attempt_count: int, error_code: str,
    ) -> TTSMetrics:
        return cls(
            job_id=job_id, message_audio_id=message_audio_id, text_chars=text_chars,
            queue_wait_ms=queue_wait_ms, attempt_count=attempt_count,
            result="failure", error_code=error_code,
        )

    def as_event(self) -> dict[str, Any]:
        realtime_factor = None
        if self.provider_total_ms is not None and self.audio_duration_ms:
            realtime_factor = round(self.provider_total_ms / self.audio_duration_ms, 3)
        return {
            "event": "tts_performance",
            "job_id": str(self.job_id),
            "message_audio_id": str(self.message_audio_id),
            "text_chars": max(0, self.text_chars),
            "queue_wait_ms": _milliseconds(self.queue_wait_ms),
            "provider_first_chunk_ms": _milliseconds(self.provider_first_chunk_ms),
            "provider_total_ms": _milliseconds(self.provider_total_ms),
            "db_write_ms": _milliseconds(self.db_write_ms),
            "storage_upload_ms": _milliseconds(self.storage_upload_ms),
            "end_to_end_ms": _milliseconds(self.end_to_end_ms),
            "audio_duration_ms": max(0, self.audio_duration_ms or 0),
            "realtime_factor": realtime_factor,
            "chunk_count": max(0, self.chunk_count),
            "attempt_count": max(0, self.attempt_count),
            "result": self.result,
            "error_code": self.error_code,
        }


def emit_tts_metrics(metrics: TTSMetrics) -> None:
    logger.info(json.dumps(metrics.as_event(), ensure_ascii=False, sort_keys=True))
