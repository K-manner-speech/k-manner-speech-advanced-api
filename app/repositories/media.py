from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.conversation import ConversationRepository
from app.schemas.rooms import MessageCreateRequest
from app.services.jobs import get_job_queue_name


class MediaRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._jobs = ConversationRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def get_audio(self, user_id: UUID, message_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text("""
                select a.id, a.audio_type, a.storage_path, a.duration_ms,
                       a.generation_status as status
                from public.message_audio a
                join public.room_messages m on m.id = a.message_id
                join public.practice_rooms r on r.id = m.room_id
                where m.id = :message_id and r.user_id = :user_id and a.is_current
                order by a.created_at desc limit 1
            """),
                {"message_id": message_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def retry_tts(
        self, user_id: UUID, message_id: UUID, deadline_seconds: int
    ) -> tuple[UUID, dict[str, Any]] | None:
        target = (
            self._session.execute(
                text("""
                select a.id, a.generation_status
                from public.message_audio a
                join public.room_messages m on m.id = a.message_id
                join public.practice_rooms r on r.id = m.room_id
                where m.id = :message_id and r.user_id = :user_id and a.is_current
                order by a.created_at desc limit 1 for update of a
            """),
                {"message_id": message_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            message = (
                self._session.execute(
                    text("""
                        select m.id, m.room_id
                        from public.room_messages m
                        join public.practice_rooms r on r.id = m.room_id
                        where m.id = :message_id and r.user_id = :user_id
                          and m.sender_type = 'persona'
                    """),
                    {"message_id": message_id, "user_id": user_id},
                )
                .mappings()
                .one_or_none()
            )
            if message is None:
                return None
            target_id = self._session.execute(
                text("""
                    insert into public.message_audio
                        (message_id, audio_type, storage_path, generation_status, deadline_at)
                    values (:message_id, 'persona_tts', :storage_path, 'processing', :deadline_at)
                    returning id
                """),
                {
                    "message_id": message_id,
                    "storage_path": f"{user_id}/{message['room_id']}/{message_id}.wav",
                    "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
                },
            ).scalar_one()
            job = self._jobs.insert_job(
                user_id, "tts_generation", "message_audio_id", target_id, deadline_seconds
            )
            self._jobs.enqueue(get_job_queue_name("tts_generation"), job["id"], user_id)
            self._session.commit()
            return target_id, job
        if target["generation_status"] != "failed":
            raise RuntimeError("audio is not retryable")
        active = self._session.execute(
            text("""
                select 1 from public.processing_jobs
                where message_audio_id = :target_id and status in ('queued', 'processing')
            """),
            {"target_id": target["id"]},
        ).first()
        if active is not None:
            raise RuntimeError("audio already has an active job")
        self._session.execute(
            text("""
                update public.message_audio
                set generation_status = 'processing', processing_token = gen_random_uuid(),
                    error_code = null, completed_at = null, deadline_at = :deadline_at,
                    next_attempt_at = null, updated_at = now()
                where id = :target_id
            """),
            {
                "target_id": target["id"],
                "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
            },
        )
        job = self._jobs.insert_job(
            user_id, "tts_generation", "message_audio_id", target["id"], deadline_seconds
        )
        self._jobs.enqueue(get_job_queue_name("tts_generation"), job["id"], user_id)
        self._session.commit()
        return target["id"], job

    def create_repeat(
        self,
        user_id: UUID,
        source_message_id: UUID,
        expression: str,
        client_request_id: UUID,
        deadline_seconds: int,
        user_queue_limit: int,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        source = (
            self._session.execute(
                text("""
                select m.room_id
                from public.room_messages m
                join public.practice_rooms r on r.id = m.room_id
                where m.id = :message_id and r.user_id = :user_id
                  and exists (
                    select 1 from public.turn_feedback f
                    join public.feedback_scores s on s.feedback_id = f.id
                    where f.message_id = m.id and s.recommended_expression = :expression
                  )
            """),
                {"message_id": source_message_id, "user_id": user_id, "expression": expression},
            )
            .mappings()
            .one_or_none()
        )
        if source is None:
            return None
        return self._jobs.create_message_and_job(
            user_id,
            source["room_id"],
            MessageCreateRequest(
                content=expression,
                input_mode="text",
                client_request_id=client_request_id,
            ),
            deadline_seconds,
            user_queue_limit,
        )

    def create_voice_message(
        self,
        user_id: UUID,
        room_id: UUID,
        request: MessageCreateRequest,
        storage_path: str,
        deadline_seconds: int,
        user_queue_limit: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        message, job = self._jobs.create_message_and_job(
            user_id, room_id, request, deadline_seconds, user_queue_limit
        )
        self._session.execute(
            text("""
                insert into public.message_audio
                    (message_id, audio_type, storage_path, generation_status, is_current,
                     completed_at, deadline_at)
                values (:message_id, 'user_recording', :storage_path, 'ready', true, now(), now())
            """),
            {"message_id": message["id"], "storage_path": storage_path},
        )
        self._session.commit()
        return message, job
