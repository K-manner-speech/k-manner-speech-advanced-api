from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.conversation import ConversationRepository
from app.services.jobs import get_job_queue_name


class ResultRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._jobs = ConversationRepository(session)

    def get_by_room(self, user_id: UUID, room_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text("""
                select s.id, s.room_id, s.attempt_no, r.practice_type,
                       case when r.practice_type = 'interview'
                            then '면접 자기소개' else r.title end as display_title,
                       s.result_status as status,
                       (select j.error_code from public.processing_jobs j
                        where j.session_result_id = s.id
                        order by j.created_at desc, j.id desc limit 1) as failure_code,
                       s.missing_categories, s.created_at, s.overall_score,
                       s.summary, s.interview_setup_snapshot
                from public.session_results s
                join public.practice_rooms r on r.id = s.room_id
                where s.room_id = :room_id and r.user_id = :user_id
                order by s.attempt_no desc limit 1
            """),
                {"room_id": room_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        return self._with_items(row)

    def get(self, user_id: UUID, result_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text("""
                select s.id, s.room_id, s.attempt_no, r.practice_type,
                       case when r.practice_type = 'interview'
                            then '면접 자기소개' else r.title end as display_title,
                       s.result_status as status,
                       (select j.error_code from public.processing_jobs j
                        where j.session_result_id = s.id
                        order by j.created_at desc, j.id desc limit 1) as failure_code,
                       s.missing_categories, s.created_at, s.overall_score,
                       s.summary, s.interview_setup_snapshot
                from public.session_results s
                join public.practice_rooms r on r.id = s.room_id
                where s.id = :result_id and s.user_id = :user_id
            """),
                {"result_id": result_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        return self._with_items(row)

    def list(self, user_id: UUID, limit: int) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text("""
                select s.id, s.room_id, s.attempt_no, r.practice_type,
                       case when r.practice_type = 'interview'
                            then '면접 자기소개' else r.title end as display_title,
                       s.result_status as status,
                       (select j.error_code from public.processing_jobs j
                        where j.session_result_id = s.id
                        order by j.created_at desc, j.id desc limit 1) as failure_code,
                       s.missing_categories, s.overall_score, s.summary,
                       s.created_at
                from public.session_results s
                join public.practice_rooms r on r.id = s.room_id
                where s.user_id = :user_id
                order by s.created_at desc, s.id desc limit :limit
            """),
            {"user_id": user_id, "limit": limit},
        ).mappings()
        return [
            {
                **dict(row),
                "overall_score": int(row["overall_score"])
                if row["overall_score"] is not None
                else None,
            }
            for row in rows
        ]

    def retry(
        self, user_id: UUID, room_id: UUID, deadline_seconds: int
    ) -> tuple[UUID, dict[str, Any]] | None:
        target = (
            self._session.execute(
                text("""
                select r.id as room_id, r.practice_type,
                       r.interview_configuration_id,
                       s.id, s.result_status
                from public.practice_rooms r
                left join lateral (
                    select sr.id, sr.result_status
                    from public.session_results sr
                    where sr.room_id = r.id
                    order by sr.attempt_no desc limit 1
                ) s on true
                where r.id = :room_id and r.user_id = :user_id
                  and r.status = 'completed'
                for update of r
            """),
                {"room_id": room_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            return None
        if target["id"] is None:
            target_id = self._session.execute(
                text(
                    """
                    insert into public.session_results
                        (room_id, user_id, result_status, interview_setup_snapshot)
                    values (:room_id, :user_id, 'processing',
                            case when :practice_type = 'interview'
                                 then jsonb_build_object(
                                     'configuration_id',
                                     cast(:configuration_id as text))
                                 else null end)
                    returning id
                    """
                ),
                {
                    "room_id": target["room_id"],
                    "user_id": user_id,
                    "practice_type": target["practice_type"],
                    "configuration_id": target["interview_configuration_id"],
                },
            ).scalar_one()
        elif target["result_status"] != "failed":
            raise RuntimeError("result is not retryable")
        else:
            target_id = target["id"]
            active = self._session.execute(
                text("""
                    select 1 from public.processing_jobs
                    where session_result_id = :target_id
                      and status in ('queued', 'processing')
                """),
                {"target_id": target_id},
            ).first()
            if active is not None:
                raise RuntimeError("result already has an active job")
            self._session.execute(
                text("""
                    update public.session_results
                    set result_status = 'processing', updated_at = now()
                    where id = :target_id
                """),
                {"target_id": target_id},
            )
        job = self._jobs.insert_job(
            user_id,
            "session_result_generation",
            "session_result_id",
            target_id,
            deadline_seconds,
        )
        self._jobs.enqueue(
            get_job_queue_name("session_result_generation"), job["id"], user_id
        )
        self._session.commit()
        return target_id, job

    def delete(self, user_id: UUID, result_id: UUID) -> bool:
        active = self._session.execute(
            text("""
                select 1 from public.processing_jobs j
                join public.session_results s on s.id = j.session_result_id
                where s.id = :result_id and s.user_id = :user_id
                  and j.status in ('queued', 'processing')
            """),
            {"result_id": result_id, "user_id": user_id},
        ).first()
        if active is not None:
            raise RuntimeError("result has an active job")
        row = self._session.execute(
            text(
                """
                delete from public.session_results
                where id = :result_id and user_id = :user_id
                returning id
                """
            ),
            {"result_id": result_id, "user_id": user_id},
        ).first()
        self._session.commit()
        return row is not None

    def _with_items(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        items = self._session.execute(
            text("""
                select item_type, category, title, original_expression,
                       recommended_expression, explanation, evidence_text as evidence,
                       source_document_id, sort_order as "order"
                from public.result_items where result_id = :result_id
                order by sort_order, id
            """),
            {"result_id": row["id"]},
        ).mappings()
        result = dict(row)
        # 일반 결과의 항목별 점수. 면접 결과에는 비어 있고 아래 평가가 대신 쓰인다.
        general_scores = [
            {**dict(score), "score": int(score["score"])}
            for score in self._session.execute(
                text(
                    """
                    select category, score, 25 as max_score,
                           strength_text as strength,
                           suggestion_text as suggestion,
                           evidence_text as evidence
                    from public.general_evaluation_scores
                    where result_id = :result_id
                    order by category
                    """
                ),
                {"result_id": row["id"]},
            ).mappings()
        ]
        interview_evaluation = None
        if result.pop("interview_setup_snapshot", None) is not None:
            score_rows = list(
                self._session.execute(
                    text(
                        """
                        select category, score, 20 as max_score,
                               strength_text as strength,
                               suggestion_text as suggestion,
                               evidence_text as evidence
                        from public.interview_evaluation_scores
                        where result_id = :result_id
                        order by category
                        """
                    ),
                    {"result_id": result["id"]},
                ).mappings()
            )
            interview_evaluation = {
                "status": result["status"],
                "overall_score": int(result["overall_score"])
                if result["overall_score"] is not None
                else None,
                "summary": result["summary"],
                "scores": [
                    {**dict(score), "score": int(score["score"])} for score in score_rows
                ],
                "missing_categories": result["missing_categories"],
            }
        if result["overall_score"] is not None:
            result["overall_score"] = int(result["overall_score"])
        return {
            **result,
            "items": [dict(item) for item in items],
            "scores": general_scores,
            "source_refs": [],
            "interview_evaluation": interview_evaluation,
        }
