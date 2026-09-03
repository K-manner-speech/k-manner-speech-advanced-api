from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.rooms import MessageCreateRequest, RoomCreateRequest
from app.services.jobs import get_job_queue_name, get_job_target_columns


class InterviewQuestionModeError(ValueError):
    pass


class InterviewQuestionOrderError(ValueError):
    pass


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_active_room(
        self,
        authenticated_user_id: UUID,
        request: RoomCreateRequest,
    ) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text(
                    """
                select id, title, practice_type, persona_id, scenario_id, status,
                       turn_count, ended_reason, started_at, completed_at, updated_at
                from public.practice_rooms
                where user_id = :authenticated_user_id
                  and practice_type = :practice_type
                  and persona_id is not distinct from :persona_id
                  and scenario_id is not distinct from :scenario_id
                  and status = 'in_progress'
                """
                ),
                {
                    "authenticated_user_id": authenticated_user_id,
                    **request.model_dump(),
                },
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def validate_catalog(self, request: RoomCreateRequest) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text(
                    """
                select p.name as persona_name, s.title as scenario_title, s.goal,
                       s.opening_message
                from public.personas p
                left join public.scenarios s
                  on s.id = :scenario_id and s.is_active = true
                left join public.persona_scenarios ps
                  on ps.persona_id = p.id and ps.scenario_id = s.id
                where p.id = :persona_id and p.is_active = true
                  and (
                    (:practice_type = 'free_chat' and :scenario_id is null)
                    or
                    (:practice_type = 'scenario' and s.id is not null and ps.persona_id is not null)
                  )
                """
                ),
                request.model_dump(),
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def create_room(
        self,
        authenticated_user_id: UUID,
        request: RoomCreateRequest,
        catalog: dict[str, Any],
    ) -> dict[str, Any]:
        title = catalog["scenario_title"] or catalog["persona_name"]
        row = (
            self._session.execute(
                text(
                    """
                insert into public.practice_rooms
                    (user_id, practice_type, persona_id, scenario_id, title, goal_snapshot)
                values
                    (:authenticated_user_id, :practice_type, :persona_id, :scenario_id,
                     :title, :goal)
                returning id, title, practice_type, persona_id, scenario_id, status,
                          turn_count, ended_reason, started_at, completed_at, updated_at
                """
                ),
                {
                    "authenticated_user_id": authenticated_user_id,
                    **request.model_dump(),
                    "title": title,
                    "goal": catalog["goal"],
                },
            )
            .mappings()
            .one()
        )
        opening_message = catalog.get("opening_message")
        if opening_message:
            self._session.execute(
                text(
                    """
                insert into public.room_messages
                    (room_id, sequence_no, sender_type, content, delivery_status,
                     persona_emotion)
                values (:room_id, 1, 'persona', :content, 'sent', 'neutral')
                """
                ),
                {"room_id": row["id"], "content": opening_message},
            )
        return dict(row)

    def list_rooms(
        self,
        authenticated_user_id: UUID,
        limit: int,
        status: str | None,
        practice_type: str | None,
    ) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text(
                """
                select id, title, practice_type, persona_id, scenario_id, status,
                       turn_count, ended_reason, started_at, completed_at, updated_at
                from public.practice_rooms
                where user_id = :authenticated_user_id
                  and (
                    cast(:status as text) is null
                    or status = cast(:status as text)
                  )
                  and (
                    cast(:practice_type as text) is null
                    or practice_type = cast(:practice_type as text)
                  )
                order by updated_at desc, id desc
                limit :limit
                """
            ),
            {
                "authenticated_user_id": authenticated_user_id,
                "limit": limit,
                "status": status,
                "practice_type": practice_type,
            },
        ).mappings()
        return [dict(row) for row in rows]

    def get_room(self, authenticated_user_id: UUID, room_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text(
                    """
                select r.id, r.title, r.practice_type, r.persona_id, r.scenario_id, r.status,
                       r.turn_count, r.ended_reason, r.started_at, r.completed_at, r.updated_at,
                       r.goal_snapshot as goal, p.name as persona_name,
                       r.interview_configuration_id,
                       case when r.practice_type = 'interview' then (
                         select q.id
                         from public.interview_questions q
                         where q.configuration_id = r.interview_configuration_id
                           and not exists (
                             select 1 from public.interview_answers a
                             where a.question_id = q.id and a.room_id = r.id
                               and a.is_current
                           )
                         order by q.sequence_no, q.id
                         limit 1
                       ) end as current_interview_question_id
                from public.practice_rooms r
                left join public.personas p on p.id = r.persona_id
                where r.id = :room_id and r.user_id = :authenticated_user_id
                """
                ),
                {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def list_room_storage_paths(self, authenticated_user_id: UUID, room_id: UUID) -> list[str]:
        """방에 속한 음성 파일 경로. 방을 지우기 전에 불러야 한다.

        TTS와 사용자 녹음 모두 message-audio 버킷의 {user_id}/{room_id}/ 아래에
        저장되므로, message_audio 레코드가 없는 파일까지 접두어로 찾는다.
        """
        rows = self._session.execute(
            text(
                """
                select name
                from storage.objects
                where bucket_id = 'message-audio' and name like :room_prefix
                """
            ),
            {"room_prefix": f"{authenticated_user_id}/{room_id}/%"},
        ).scalars()
        return [str(row) for row in rows]

    def delete_room(self, authenticated_user_id: UUID, room_id: UUID) -> bool:
        self._session.execute(
            text(
                """
                update public.processing_jobs j
                set status = 'cancelled', completed_at = now(), updated_at = now()
                where j.user_id = :authenticated_user_id
                  and j.status in ('queued', 'processing')
                  and exists (
                    select 1
                    from public.room_messages m
                    left join public.message_ai_processing a on a.message_id = m.id
                    left join public.message_emotion_analysis e on e.message_id = m.id
                    left join public.message_audio au on au.message_id = m.id
                    left join public.turn_feedback f on f.message_id = m.id
                    where m.room_id = :room_id
                      and (j.message_ai_processing_id = a.id
                        or j.message_emotion_analysis_id = e.id
                        or j.message_audio_id = au.id
                        or j.turn_feedback_id = f.id)
                  )
                """
            ),
            {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
        )
        result = self._session.execute(
            text(
                """
                delete from public.practice_rooms
                where id = :room_id and user_id = :authenticated_user_id
                returning id
                """
            ),
            {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
        )
        return result.scalar_one_or_none() is not None

    def list_messages(
        self, authenticated_user_id: UUID, room_id: UUID, limit: int
    ) -> list[dict[str, Any]] | None:
        if self.get_room(authenticated_user_id, room_id) is None:
            return None
        rows = self._session.execute(
            text(
                """
                select m.id, m.room_id, m.sequence_no, m.sender_type, m.content,
                       m.input_mode, m.delivery_status, m.reply_to_message_id,
                       m.created_at, m.updated_at,
                       case
                           when m.sender_type = 'persona' and m.persona_emotion is not null
                           then 'succeeded'
                           else e.processing_status
                       end as emotion_status,
                       case
                           when m.sender_type = 'persona' then m.persona_emotion
                           else e.emotion_label
                       end as emotion_label,
                       case when m.sender_type = 'persona' then null else e.reasoning end
                           as reasoning
                from public.room_messages m
                left join public.message_emotion_analysis e on e.message_id = m.id
                where m.room_id = :room_id
                order by m.sequence_no, m.id
                limit :limit
                """
            ),
            {"room_id": room_id, "limit": limit},
        ).mappings()
        return [dict(row) for row in rows]

    def create_message_and_job(
        self,
        authenticated_user_id: UUID,
        room_id: UUID,
        request: MessageCreateRequest,
        deadline_seconds: int,
        user_queue_limit: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        room = (
            self._session.execute(
                text(
                    """
                select id, status, practice_type, interview_configuration_id, ended_reason
                from public.practice_rooms
                where id = :room_id and user_id = :authenticated_user_id
                for update
                """
                ),
                {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        if room is None:
            raise LookupError("room not found")
        if room["status"] != "in_progress":
            raise RuntimeError("room is not active")
        if room["ended_reason"] == "awaiting_user_end":
            raise RuntimeError("interview is awaiting manual completion")

        question_id = request.current_interview_question_id
        if room["practice_type"] == "interview":
            next_question_id = self._session.execute(
                text(
                    """
                    select q.id
                    from public.interview_questions q
                    where q.configuration_id = :configuration_id
                      and not exists (
                        select 1 from public.interview_answers a
                        where a.question_id = q.id and a.room_id = :room_id
                          and a.is_current
                      )
                    order by q.sequence_no, q.id
                    limit 1
                    for update of q
                    """
                ),
                {
                    "configuration_id": room["interview_configuration_id"],
                    "room_id": room_id,
                },
            ).scalar_one_or_none()
            if question_id is None and next_question_id is not None:
                raise InterviewQuestionModeError("interview question is required")
            if question_id is not None and next_question_id != question_id:
                raise InterviewQuestionOrderError("interview question is out of order")
        elif question_id is not None:
            raise InterviewQuestionModeError("question is not allowed for this room")

        active_jobs = self._session.execute(
            text(
                """
                select count(*) from public.processing_jobs
                where user_id = :authenticated_user_id
                  and status in ('queued', 'processing')
                """
            ),
            {"authenticated_user_id": authenticated_user_id},
        ).scalar_one()
        if active_jobs >= user_queue_limit:
            raise OverflowError("user queue limit exceeded")

        sequence_no = self._session.execute(
            text(
                "select coalesce(max(sequence_no), 0) + 1 from public.room_messages "
                "where room_id = :room_id"
            ),
            {"room_id": room_id},
        ).scalar_one()
        message_row = (
            self._session.execute(
                text(
                    """
                insert into public.room_messages
                    (room_id, sequence_no, sender_type, content, input_mode,
                     delivery_status, transcript_confirmed, client_request_id)
                values
                    (:room_id, :sequence_no, 'user', :content, :input_mode,
                     'sent', true, :client_request_id)
                returning id, room_id, sequence_no, sender_type, content, input_mode,
                          delivery_status, reply_to_message_id, created_at, updated_at
                """
                ),
                {"room_id": room_id, "sequence_no": sequence_no, **request.model_dump()},
            )
            .mappings()
            .one()
        )
        if question_id is not None:
            self._session.execute(
                text(
                    """
                    insert into public.interview_answers
                        (question_id, room_id, message_id, answer_attempt_no, is_current)
                    values (
                        :question_id, :room_id, :message_id,
                        coalesce((select max(answer_attempt_no) + 1
                                  from public.interview_answers
                                  where question_id = :question_id and room_id = :room_id), 1),
                        false
                    )
                    """
                ),
                {
                    "question_id": question_id,
                    "room_id": room_id,
                    "message_id": message_row["id"],
                },
            )
        processing_id = self._session.execute(
            text(
                """
                insert into public.message_ai_processing
                    (message_id, processing_status, deadline_at)
                values (:message_id, 'processing', :deadline_at)
                returning id
                """
            ),
            {
                "message_id": message_row["id"],
                "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
            },
        ).scalar_one()
        job_row = self.insert_job(
            authenticated_user_id,
            "conversation_text",
            "message_ai_processing_id",
            processing_id,
            deadline_seconds,
        )
        self.enqueue(
            get_job_queue_name("conversation_text"), job_row["id"], authenticated_user_id
        )
        return dict(message_row), job_row

    def insert_job(
        self,
        authenticated_user_id: UUID,
        job_type: str,
        target_column: str,
        target_id: UUID,
        deadline_seconds: int,
    ) -> dict[str, Any]:
        if target_column not in get_job_target_columns():
            raise ValueError("unsupported job target")
        job_id = uuid4()
        row = (
            self._session.execute(
                text(
                    f"""
                insert into public.processing_jobs
                    (id, user_id, job_type, status, {target_column}, deadline_at)
                values
                    (:job_id, :authenticated_user_id, :job_type, 'queued',
                     :target_id, :deadline_at)
                returning id, job_type as type, status, progress_stage,
                          completed_units, total_units, error_code, error_retryable,
                          error_meta, created_at, updated_at
                """
                ),
                {
                    "job_id": job_id,
                    "authenticated_user_id": authenticated_user_id,
                    "job_type": job_type,
                    "target_id": target_id,
                    "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
                },
            )
            .mappings()
            .one()
        )
        return dict(row)

    def enqueue(self, queue_name: str, job_id: UUID, user_id: UUID) -> None:
        self._session.execute(
            text("select pgmq.send(:queue_name, cast(:payload as jsonb))"),
            {
                "queue_name": queue_name,
                "payload": json.dumps({"job_id": str(job_id), "user_id": str(user_id)}),
            },
        )

    def get_message(self, authenticated_user_id: UUID, message_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text(
                    """
                select m.id, m.room_id, m.sequence_no, m.sender_type, m.content,
                       m.input_mode, m.delivery_status, m.reply_to_message_id,
                       m.created_at, m.updated_at
                from public.room_messages m
                join public.practice_rooms r on r.id = m.room_id
                where m.id = :message_id and r.user_id = :authenticated_user_id
                """
                ),
                {"message_id": message_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def get_job(self, authenticated_user_id: UUID, job_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text(
                    """
                select id, job_type as type, status, progress_stage, completed_units,
                       total_units, error_code, error_retryable, error_meta,
                       created_at, updated_at
                from public.processing_jobs
                where id = :job_id and user_id = :authenticated_user_id
                """
                ),
                {"job_id": job_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def complete_interview(
        self, authenticated_user_id: UUID, room_id: UUID, deadline_seconds: int
    ) -> dict[str, Any] | None:
        target = (
            self._session.execute(
                text(
                    """
                    select id, interview_configuration_id
                    from public.practice_rooms
                    where id = :room_id and user_id = :authenticated_user_id
                      and practice_type = 'interview' and status = 'in_progress'
                      and ended_reason = 'awaiting_user_end'
                    for update
                    """
                ),
                {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            return None
        row = (
            self._session.execute(
                text(
                    """
                    update public.practice_rooms
                    set status = 'completed', ended_reason = 'completed',
                        completed_at = now(), updated_at = now()
                    where id = :room_id and user_id = :authenticated_user_id
                    returning id, title, practice_type, persona_id, scenario_id, status,
                              turn_count, ended_reason, started_at, completed_at, updated_at
                    """
                ),
                {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one()
        )
        self._session.execute(
            text(
                """
                update public.interview_configurations
                set status = 'completed', completed_at = now(), updated_at = now()
                where id = :configuration_id and user_id = :authenticated_user_id
                """
            ),
            {
                "configuration_id": target["interview_configuration_id"],
                "authenticated_user_id": authenticated_user_id,
            },
        )
        result_id = self._session.execute(
            text(
                """
                insert into public.session_results
                    (room_id, user_id, result_status, interview_setup_snapshot)
                values (:room_id, :authenticated_user_id, 'processing',
                        jsonb_build_object('configuration_id', cast(:configuration_id as text)))
                returning id
                """
            ),
            {
                "room_id": room_id,
                "authenticated_user_id": authenticated_user_id,
                "configuration_id": target["interview_configuration_id"],
            },
        ).scalar_one()
        job = self.insert_job(
            authenticated_user_id,
            "session_result_generation",
            "session_result_id",
            result_id,
            deadline_seconds,
        )
        self.enqueue(
            get_job_queue_name("session_result_generation"), job["id"], authenticated_user_id
        )
        return dict(row)

    def complete_scenario(
        self, authenticated_user_id: UUID, room_id: UUID, deadline_seconds: int
    ) -> dict[str, Any] | None:
        target = (
            self._session.execute(
                text(
                    """
                    select id
                    from public.practice_rooms
                    where id = :room_id and user_id = :authenticated_user_id
                      and practice_type in ('scenario', 'free_chat')
                      and status = 'in_progress'
                    for update
                    """
                ),
                {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            return None
        row = (
            self._session.execute(
                text(
                    """
                    update public.practice_rooms
                    set status = 'completed', ended_reason = 'completed',
                        completed_at = now(), updated_at = now()
                    where id = :room_id and user_id = :authenticated_user_id
                    returning id, title, practice_type, persona_id, scenario_id, status,
                              turn_count, ended_reason, started_at, completed_at, updated_at
                    """
                ),
                {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one()
        )
        result_id = self._session.execute(
            text(
                """
                insert into public.session_results
                    (room_id, user_id, result_status)
                values (:room_id, :authenticated_user_id, 'processing')
                returning id
                """
            ),
            {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
        ).scalar_one()
        job = self.insert_job(
            authenticated_user_id,
            "session_result_generation",
            "session_result_id",
            result_id,
            deadline_seconds,
        )
        self.enqueue(
            get_job_queue_name("session_result_generation"), job["id"], authenticated_user_id
        )
        return dict(row)

    def dismiss_goal_prompt(
        self, authenticated_user_id: UUID, room_id: UUID
    ) -> dict[str, Any] | None:
        """사용자가 "계속하기"를 선택했다. 남은 턴 동안 다시 판정하지 않는다."""
        row = (
            self._session.execute(
                text(
                    """
                    update public.practice_rooms
                    set ended_reason = null, goal_prompt_dismissed_at = now(),
                        updated_at = now()
                    where id = :room_id and user_id = :authenticated_user_id
                      and status = 'in_progress' and ended_reason = 'goal_achieved'
                    returning id, title, practice_type, persona_id, scenario_id, status,
                              turn_count, ended_reason, started_at, completed_at, updated_at
                    """
                ),
                {"room_id": room_id, "authenticated_user_id": authenticated_user_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def retry_response(
        self,
        authenticated_user_id: UUID,
        message_id: UUID,
        deadline_seconds: int,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        target = (
            self._session.execute(
                text(
                    """
                select a.id, a.processing_status
                from public.message_ai_processing a
                join public.room_messages m on m.id = a.message_id
                join public.practice_rooms r on r.id = m.room_id
                where m.id = :message_id and r.user_id = :authenticated_user_id
                for update of a
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
            raise RuntimeError("response is not retryable")

        active_job = self._session.execute(
            text(
                """
                select 1 from public.processing_jobs
                where message_ai_processing_id = :target_id
                  and status in ('queued', 'processing')
                """
            ),
            {"target_id": target["id"]},
        ).first()
        if active_job is not None:
            raise RuntimeError("response already has an active job")

        self._session.execute(
            text(
                """
                update public.message_ai_processing
                set processing_status = 'processing', processing_token = gen_random_uuid(),
                    error_code = null, error_message = null, completed_at = null,
                    deadline_at = :deadline_at, next_attempt_at = null,
                    updated_at = now()
                where id = :target_id
                """
            ),
            {
                "target_id": target["id"],
                "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
            },
        )
        job = self.insert_job(
            authenticated_user_id,
            "conversation_text",
            "message_ai_processing_id",
            target["id"],
            deadline_seconds,
        )
        self.enqueue(
            get_job_queue_name("conversation_text"), job["id"], authenticated_user_id
        )
        message = self.get_message(authenticated_user_id, message_id)
        if message is None:
            raise LookupError("message disappeared")
        return message, job

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
