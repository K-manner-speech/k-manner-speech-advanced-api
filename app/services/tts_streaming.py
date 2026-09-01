from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker


class TTSStreamRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve(self, user_id: UUID, message_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text("""
                select a.id, a.processing_token, a.generation_status
                from public.message_audio a
                join public.room_messages m on m.id = a.message_id
                join public.practice_rooms r on r.id = m.room_id
                where m.id = :message_id and r.user_id = :user_id
                  and m.sender_type = 'persona' and a.audio_type = 'persona_tts'
                  and a.is_current
                order by a.created_at desc limit 1
            """),
                {"message_id": message_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None


def resolve_tts_stream_target(
    session_factory: sessionmaker[Session],
    user_id: UUID,
    message_id: UUID,
) -> dict[str, Any] | None:
    with session_factory() as session:
        return TTSStreamRepository(session).resolve(user_id, message_id)


def iter_tts_pcm(
    session_factory: sessionmaker[Session],
    message_audio_id: UUID,
    processing_token: UUID,
    *,
    timeout_seconds: float = 50,
    poll_seconds: float = 0.05,
) -> Iterator[bytes]:
    sequence_no = -1
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with session_factory() as session:
            rows = list(
                session.execute(
                    text("""
                    select sequence_no, pcm
                    from public.tts_stream_chunks
                    where message_audio_id = :id and processing_token = :token
                      and sequence_no > :sequence_no and expires_at > now()
                    order by sequence_no
                """),
                    {"id": message_audio_id, "token": processing_token, "sequence_no": sequence_no},
                ).mappings()
            )
            state = (
                session.execute(
                    text(
                        "select generation_status, processing_token "
                        "from public.message_audio where id = :id"
                    ),
                    {"id": message_audio_id},
                )
                .mappings()
                .one_or_none()
            )
        for row in rows:
            sequence_no = int(row["sequence_no"])
            yield bytes(row["pcm"])
        if state is None:
            return
        current_token = state["processing_token"]
        if current_token is not None and current_token != processing_token:
            processing_token = current_token
            sequence_no = -1
            continue
        status = state["generation_status"]
        if status in {"ready", "failed"} and not rows:
            return
        time.sleep(poll_seconds)
