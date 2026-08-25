from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.conversation import ConversationRepository


class FeedbackRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._jobs = ConversationRepository(session)

    def get_feedback(self, authenticated_user_id: UUID, message_id: UUID) -> dict[str, Any] | None:
        header = (
            self._session.execute(
                text(
                    """
                select f.id, f.analysis_status as status, f.overall_score,
                       f.summary, f.error_code
                from public.turn_feedback f
                join public.room_messages m on m.id = f.message_id
                join public.practice_rooms r on r.id = m.room_id
                where m.id = :message_id and r.user_id = :authenticated_user_id
                """
                ),
                {"message_id": message_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        if header is None:
            return None
        scores = self._session.execute(
            text(
                """
                select category, score, max_score, strength_text as strength,
                       suggestion_text as suggestion,
                       original_expression as original_text,
                       recommended_expression as recommended_text
                from public.feedback_scores
                where feedback_id = :feedback_id
                order by category
                """
            ),
            {"feedback_id": header["id"]},
        ).mappings()
        emotions = self._session.execute(
            text(
                """
                select emotion_label as label, percentage, sort_order,
                       analysis_source as source, evidence_text as evidence,
                       impression_text as impression
                from public.feedback_emotions
                where feedback_id = :feedback_id
                order by sort_order, id
                """
            ),
            {"feedback_id": header["id"]},
        ).mappings()
        return {
            **dict(header),
            "scores": [dict(row) for row in scores],
            "emotions": [dict(row) for row in emotions],
        }

    def retry_emotion(
        self,
        authenticated_user_id: UUID,
        message_id: UUID,
        deadline_seconds: int,
    ) -> tuple[UUID, dict[str, Any]] | None:
        target = (
            self._session.execute(
                text(
                    """
                select e.id, e.processing_status
                from public.message_emotion_analysis e
                join public.room_messages m on m.id = e.message_id
                join public.practice_rooms r on r.id = m.room_id
                where m.id = :message_id and r.user_id = :authenticated_user_id
                for update of e
                """
                ),
                {"message_id": message_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            return None
        if target["processing_status"] != "failed":
            raise RuntimeError("emotion is not retryable")
        self._assert_no_active_job("message_emotion_analysis_id", target["id"])
        self._session.execute(
            text(
                """
                update public.message_emotion_analysis
                set processing_status = 'processing', processing_token = gen_random_uuid(),
                    emotion_label = null, reasoning = null, error_code = null,
                    completed_at = null, deadline_at = :deadline_at,
                    next_attempt_at = null, updated_at = now()
                where id = :target_id
                """
            ),
            {
                "target_id": target["id"],
                "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
            },
        )
        job = self._jobs.insert_job(
            authenticated_user_id,
            "emotion_analysis",
            "message_emotion_analysis_id",
            target["id"],
            deadline_seconds,
        )
        self._jobs.enqueue("interactive_ai", job["id"], authenticated_user_id)
        return target["id"], job

    def retry_feedback(
        self,
        authenticated_user_id: UUID,
        message_id: UUID,
        deadline_seconds: int,
    ) -> tuple[UUID, dict[str, Any]] | None:
        target = (
            self._session.execute(
                text(
                    """
                select f.id, f.analysis_status
                from public.turn_feedback f
                join public.room_messages m on m.id = f.message_id
                join public.practice_rooms r on r.id = m.room_id
                where m.id = :message_id and r.user_id = :authenticated_user_id
                for update of f
                """
                ),
                {"message_id": message_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            return None
        if target["analysis_status"] not in {"failed", "partial"}:
            raise RuntimeError("feedback is not retryable")
        self._assert_no_active_job("turn_feedback_id", target["id"])
        self._session.execute(
            text(
                """
                update public.turn_feedback
                set analysis_status = 'processing', processing_token = gen_random_uuid(),
                    error_code = null, deadline_at = :deadline_at,
                    next_attempt_at = null, updated_at = now()
                where id = :target_id
                """
            ),
            {
                "target_id": target["id"],
                "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
            },
        )
        job = self._jobs.insert_job(
            authenticated_user_id,
            "turn_feedback",
            "turn_feedback_id",
            target["id"],
            deadline_seconds,
        )
        self._jobs.enqueue("interactive_ai", job["id"], authenticated_user_id)
        return target["id"], job

    def _assert_no_active_job(self, target_column: str, target_id: UUID) -> None:
        if target_column not in {"message_emotion_analysis_id", "turn_feedback_id"}:
            raise ValueError("unsupported target")
        active = self._session.execute(
            text(
                f"""
                select 1 from public.processing_jobs
                where {target_column} = :target_id
                  and status in ('queued', 'processing')
                """
            ),
            {"target_id": target_id},
        ).first()
        if active is not None:
            raise RuntimeError("target already has an active job")

    def commit(self) -> None:
        self._session.commit()
