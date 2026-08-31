from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from worker.queue import ClaimedJob


class TTSChunkWriter:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def reset(self, message_audio_id: UUID) -> None:
        with self._session_factory() as session:
            session.execute(
                text(
                    "delete from public.tts_stream_chunks "
                    "where expires_at <= now() or message_audio_id = :id"
                ),
                {"id": message_audio_id},
            )
            session.commit()

    def append(self, item: ClaimedJob, sequence_no: int, pcm: bytes) -> None:
        with self._session_factory() as session:
            session.execute(
                text("""
                    insert into public.tts_stream_chunks
                      (message_audio_id, processing_token, sequence_no, pcm)
                    values (:id, :token, :sequence_no, :pcm)
                    on conflict do nothing
                """),
                {
                    "id": item.target_id,
                    "token": item.processing_token,
                    "sequence_no": sequence_no,
                    "pcm": pcm,
                },
            )
            session.commit()
