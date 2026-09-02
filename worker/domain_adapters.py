from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.storage import StorageObjectStore
from app.ai.interfaces import AIProviderError
from app.ai.schemas import (
    EmotionAnalysis,
    GeneralFeedback,
    InterviewEvaluation,
    ScenarioGoalProgress,
)
from app.schemas.common import JobType
from app.services.jobs import get_job_execution_policy
from worker.executors import (
    ConfigurationOutput,
    ConversationOutput,
    DocumentAnalysisOutput,
    FinalSessionOutput,
    TTSOutput,
)
from worker.queue import ClaimedJob
from worker.runtime import JOB_QUEUE_NAMES
from worker.sql_queue import TARGET_COLUMNS, TARGET_STATE, TargetClaim


def _target_id(job: Mapping[str, Any], job_type: JobType) -> UUID:
    target = job[TARGET_COLUMNS[job_type]]
    if target is None:
        raise RuntimeError("job target is missing")
    return UUID(str(target))


def _insert_job(
    session: Session,
    *,
    user_id: UUID,
    job_type: JobType,
    target_id: UUID,
) -> UUID:
    policy = get_job_execution_policy(job_type)
    target_column = TARGET_COLUMNS[job_type]
    raw_job_id = session.execute(
        text(
            f"""
            insert into public.processing_jobs
                (user_id, job_type, status, {target_column}, deadline_at)
            values
                (:user_id, :job_type, 'queued', :target_id,
                 now() + make_interval(secs => :deadline_seconds))
            returning id
            """
        ),
        {
            "user_id": user_id,
            "job_type": job_type.value,
            "target_id": target_id,
            "deadline_seconds": policy.deadline_seconds,
        },
    ).scalar_one()
    job_id = UUID(str(raw_job_id))
    session.execute(
        text("select pgmq.send(:queue, cast(:payload as jsonb))"),
        {
            "queue": JOB_QUEUE_NAMES[job_type],
            "payload": json.dumps(
                {"job_id": str(job_id), "user_id": str(user_id)}
            ),
        },
    )
    return job_id


class ConversationAdapter:
    job_type = JobType.CONVERSATION_TEXT

    def __init__(self, storage: StorageObjectStore | None = None) -> None:
        self._storage = storage

    def claim(self, session: Session, job: Mapping[str, Any]) -> TargetClaim | None:
        target_id = _target_id(job, self.job_type)
        row = (
            session.execute(
                text(
                    """
                    select a.id, a.processing_token, m.id as message_id, m.room_id,
                           m.content, m.sequence_no, r.practice_type, r.title,
                           r.persona_id, r.scenario_id, r.interview_configuration_id,
                           p.name as persona_name, p.role_title,
                           p.prompt_bundle_key as persona_prompt_bundle,
                           ps.role_key,
                           s.goal as scenario_goal,
                           coalesce(c.summary_text, '') as context_summary,
                           c.summarized_through_message_id,
                           recording.storage_path as recording_path,
                           answer.id as interview_answer_id,
                           answer.answer_attempt_no as interview_answer_attempt_no,
                           question.id as interview_question_id,
                           question.question_text as interview_question_text,
                           question.evaluation_focus as interview_question_evaluation_focus,
                           question.sequence_no as interview_question_sequence,
                           (select count(*) from public.interview_questions iq
                            where iq.configuration_id = r.interview_configuration_id)
                             as interview_question_count,
                           (select count(*) from public.interview_answers ia
                            where ia.room_id = r.id) as interview_answer_count
                    from public.message_ai_processing a
                    join public.room_messages m on m.id = a.message_id
                    join public.practice_rooms r on r.id = m.room_id
                    left join public.personas p on p.id = r.persona_id
                    left join public.scenarios s on s.id = r.scenario_id
                    left join public.persona_scenarios ps
                      on ps.persona_id = r.persona_id and ps.scenario_id = r.scenario_id
                    left join public.room_contexts c on c.room_id = r.id
                    left join public.message_audio recording on recording.message_id = m.id
                      and recording.audio_type = 'user_recording' and recording.is_current
                    left join public.interview_answers answer on answer.message_id = m.id
                    left join public.interview_questions question
                      on question.id = answer.question_id
                    where a.id = :target_id and a.processing_status = 'processing'
                      and r.user_id = :user_id and r.status = 'in_progress'
                    for update of a, r
                    """
                ),
                {"target_id": target_id, "user_id": job["user_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        messages = list(
            session.execute(
                text(
                    """
                    select id, sequence_no, sender_type, content
                    from public.room_messages
                    where room_id = :room_id
                      and (
                        cast(:through_message_id as uuid) is null
                        or sequence_no > coalesce((
                          select sequence_no from public.room_messages
                          where id = cast(:through_message_id as uuid)
                            and room_id = :room_id
                        ), 0)
                      )
                    order by sequence_no, id
                    """
                ),
                {
                    "room_id": row["room_id"],
                    "through_message_id": row["summarized_through_message_id"],
                },
            ).mappings()
        )
        payload = {
            "room": {
                "id": str(row["room_id"]),
                "practice_type": row["practice_type"],
                "title": row["title"],
                "persona": {
                    "name": row["persona_name"],
                    "role": row["role_title"],
                    "prompt_bundle": row["persona_prompt_bundle"],
                },
                # 역할은 (페르소나, 시나리오) 조합마다 달라 번들에 넣을 수 없다.
                # DB 는 어떤 역할인지만 가리키고 내용은 roles 조각이 담는다.
                "role": row["role_key"],
                "scenario_goal": row["scenario_goal"],
            },
            "context_summary": row["context_summary"],
            "messages": [dict(message) for message in messages],
            "current_user_message_id": str(row["message_id"]),
        }
        if row["practice_type"] == "interview" and row["interview_question_id"] is not None:
            payload["current_interview_question"] = {
                "id": str(row["interview_question_id"]),
                "text": row["interview_question_text"],
                "evaluation_focus": row["interview_question_evaluation_focus"],
            }
            payload["current_interview_answer_attempt_no"] = int(
                row["interview_answer_attempt_no"]
            )
            question_count = int(row["interview_question_count"] or 0)
            answer_count = int(row["interview_answer_count"] or 0)
            payload["interview_answer_limit_reached"] = (
                question_count > 0 and answer_count >= question_count * 3
            )
            next_question = session.execute(
                text(
                    """
                    select id, question_text
                    from public.interview_questions
                    where configuration_id = :configuration_id
                      and sequence_no > :current_sequence
                    order by sequence_no, id
                    limit 1
                    """
                ),
                {
                    "configuration_id": row["interview_configuration_id"],
                    "current_sequence": row["interview_question_sequence"],
                },
            ).mappings().one_or_none()
            payload["next_interview_question"] = (
                {"id": str(next_question["id"]), "text": next_question["question_text"]}
                if next_question is not None else None
            )
        elif row["practice_type"] == "interview":
            payload["interview_closing_response"] = True
        if row.get("recording_path") and self._storage is not None:
            path = str(row["recording_path"])
            payload["audio_bytes"] = self._storage.download("message-audio", path)
            payload["audio_mime_type"] = (
                "audio/webm" if path.endswith(".webm") else
                "audio/ogg" if path.endswith(".ogg") else
                "audio/mp4" if path.endswith(".mp4") else "audio/wav"
            )
        return TargetClaim(
            target_id=target_id,
            processing_token=row["processing_token"],
            stage="context_preparing",
            payload=payload,
        )

    def complete(self, session: Session, item: ClaimedJob, output: object) -> bool:
        if not isinstance(output, ConversationOutput):
            raise TypeError("conversation output type mismatch")
        reply = output.reply
        target = (
            session.execute(
                text(
                    """
                    update public.message_ai_processing a
                    set processing_status = 'succeeded', error_code = null,
                        error_message = null, completed_at = now(), updated_at = now()
                    from public.room_messages m, public.practice_rooms r
                    where a.id = :target_id and a.processing_token = :token
                      and a.processing_status = 'processing'
                      and m.id = a.message_id and r.id = m.room_id
                      and r.user_id = :user_id and r.status = 'in_progress'
                    returning m.id as user_message_id, m.room_id, r.practice_type,
                              r.interview_configuration_id
                    """
                ),
                {
                    "target_id": item.target_id,
                    "token": item.processing_token,
                    "user_id": item.user_id,
                },
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            return False
        if target["practice_type"] == "interview":
            session.execute(
                text(
                    """
                    update public.interview_answers
                    set is_current = :is_complete
                    where message_id = :message_id and room_id = :room_id
                    """
                ),
                {
                    "is_complete": bool(
                        reply.interview_answer_complete or reply.interview_should_end
                    ),
                    "message_id": target["user_message_id"],
                    "room_id": target["room_id"],
                },
            )
        sequence_no = session.execute(
            text(
                "select coalesce(max(sequence_no), 0) + 1 "
                "from public.room_messages where room_id = :room_id"
            ),
            {"room_id": target["room_id"]},
        ).scalar_one()
        assistant_id = session.execute(
            text(
                """
                insert into public.room_messages
                    (room_id, sequence_no, sender_type, content, delivery_status,
                     persona_emotion, reply_to_message_id)
                values (:room_id, :sequence_no, 'persona', :content, 'sent',
                        :emotion, :reply_to_message_id)
                returning id
                """
            ),
            {
                "room_id": target["room_id"],
                "sequence_no": sequence_no,
                "content": reply.reply,
                "emotion": reply.persona_emotion,
                "reply_to_message_id": target["user_message_id"],
            },
        ).scalar_one()
        if output.summary is not None:
            session.execute(
                text(
                    """
                    insert into public.room_contexts
                        (room_id, summary_text, summarized_through_message_id,
                         recent_message_start_sequence)
                    values (:room_id, :summary, :through_message_id, :recent_sequence)
                    on conflict (room_id) do update
                    set summary_text = excluded.summary_text,
                        summarized_through_message_id = excluded.summarized_through_message_id,
                        recent_message_start_sequence = excluded.recent_message_start_sequence,
                        updated_at = now()
                    """
                ),
                {
                    "room_id": target["room_id"],
                    "summary": output.summary.model_dump_json(),
                    "through_message_id": output.summarized_through_message_id,
                    "recent_sequence": output.recent_message_start_sequence,
                },
            )
        self._fan_out(
            session,
            item.user_id,
            target["user_message_id"],
            assistant_id,
            target["room_id"],
            str(target["practice_type"]),
        )
        new_turn_count = session.execute(
            text(
                """
                update public.practice_rooms
                set turn_count = turn_count + 1, last_confirmed_turn_at = now(),
                    updated_at = now()
                where id = :room_id and user_id = :user_id and status = 'in_progress'
                returning turn_count
                """
            ),
            {"room_id": target["room_id"], "user_id": item.user_id},
        ).scalar_one()
        if target["practice_type"] == "interview" and reply.interview_should_end:
            session.execute(
                text(
                    """
                    update public.practice_rooms
                    set ended_reason = 'awaiting_user_end', updated_at = now()
                    where id = :room_id and user_id = :user_id and status = 'in_progress'
                    """
                ),
                {"room_id": target["room_id"], "user_id": item.user_id},
            )
        elif (
            target["practice_type"] != "interview"
            and self._should_complete(
                session, target["room_id"], str(target["practice_type"]),
                int(new_turn_count), target["interview_configuration_id"],
            )
        ):
            self._complete_room(
                session,
                item.user_id,
                target["room_id"],
                str(target["practice_type"]),
                target["interview_configuration_id"],
            )
        elif target["practice_type"] == "scenario":
            self._enqueue_goal_progress(
                session,
                item.user_id,
                target["room_id"],
                assistant_id,
                int(new_turn_count),
            )
        return True

    @staticmethod
    def _fan_out(
        session: Session,
        user_id: UUID,
        user_message_id: UUID,
        assistant_message_id: UUID,
        room_id: UUID,
        practice_type: str,
    ) -> None:
        feedback_id = None
        if practice_type != "interview":
            feedback_id = session.execute(
                text(
                    """
                    insert into public.turn_feedback
                        (message_id, analysis_status, deadline_at)
                    values (:message_id, 'processing',
                            now() + make_interval(secs => :deadline_seconds))
                    returning id
                    """
                ),
                {
                    "message_id": user_message_id,
                    "deadline_seconds": get_job_execution_policy(
                        JobType.TURN_FEEDBACK
                    ).deadline_seconds,
                },
            ).scalar_one()
        storage_path = f"{user_id}/{room_id}/{assistant_message_id}.wav"
        audio_id = session.execute(
            text(
                """
                insert into public.message_audio
                    (message_id, audio_type, storage_path, generation_status, deadline_at)
                values (:message_id, 'persona_tts', :storage_path, 'processing',
                        now() + make_interval(secs => :deadline_seconds))
                returning id
                """
            ),
            {
                "message_id": assistant_message_id,
                "storage_path": storage_path,
                "deadline_seconds": get_job_execution_policy(
                    JobType.TTS_GENERATION
                ).deadline_seconds,
            },
        ).scalar_one()
        # TTS와 피드백은 서로 독립적이다. TTS를 먼저 큐에 넣어 음성 재생
        # 시작 지연을 줄이고, 두 작업은 interactive_ai 워커에서 병렬 처리한다.
        _insert_job(
            session,
            user_id=user_id,
            job_type=JobType.TTS_GENERATION,
            target_id=audio_id,
        )
        if feedback_id is not None:
            _insert_job(
                session,
                user_id=user_id,
                job_type=JobType.TURN_FEEDBACK,
                target_id=feedback_id,
            )

    @staticmethod
    def _enqueue_goal_progress(
        session: Session,
        user_id: UUID,
        room_id: UUID,
        assistant_message_id: UUID,
        turn_count: int,
    ) -> None:
        """시나리오에서만, 2턴째부터, 아직 선택하지 않은 방에만 판정을 건다.

        1턴은 인사만 하고 끝나는 경우가 많아 판정할 것이 없다. 사용자가
        "계속하기"를 눌렀거나 이미 달성 표시가 붙은 방은 다시 묻지 않는다.
        """
        if turn_count < 2:
            return
        eligible = session.execute(
            text(
                """
                select 1
                from public.practice_rooms r
                join public.scenario_success_conditions c on c.scenario_id = r.scenario_id
                where r.id = :room_id and r.user_id = :user_id
                  and r.practice_type = 'scenario' and r.status = 'in_progress'
                  and r.ended_reason is null and r.goal_prompt_dismissed_at is null
                limit 1
                """
            ),
            {"room_id": room_id, "user_id": user_id},
        ).first()
        if eligible is None:
            return
        evaluation_id = session.execute(
            text(
                """
                insert into public.room_goal_evaluations
                    (room_id, message_id, turn_no, evaluation_status, deadline_at)
                values (:room_id, :message_id, :turn_no, 'processing',
                        now() + make_interval(secs => :deadline_seconds))
                on conflict (room_id, message_id) do nothing
                returning id
                """
            ),
            {
                "room_id": room_id,
                "message_id": assistant_message_id,
                "turn_no": turn_count,
                "deadline_seconds": get_job_execution_policy(
                    JobType.SCENARIO_GOAL_PROGRESS
                ).deadline_seconds,
            },
        ).scalar()
        if evaluation_id is None:
            return
        _insert_job(
            session,
            user_id=user_id,
            job_type=JobType.SCENARIO_GOAL_PROGRESS,
            target_id=UUID(str(evaluation_id)),
        )

    @staticmethod
    def _should_complete(
        session: Session,
        room_id: UUID,
        practice_type: str,
        turn_count: int,
        configuration_id: UUID | None,
    ) -> bool:
        if practice_type == "interview" and configuration_id is not None:
            remaining = session.execute(
                text(
                    """
                    select count(*)
                    from public.interview_questions q
                    where q.configuration_id = :configuration_id
                      and not exists (
                        select 1 from public.interview_answers a
                        where a.question_id = q.id and a.room_id = :room_id
                          and a.is_current
                      )
                    """
                ),
                {"configuration_id": configuration_id, "room_id": room_id},
            ).scalar_one()
            return int(remaining) == 0
        if practice_type == "scenario":
            max_turns = session.execute(
                text(
                    """
                    select s.max_turns
                    from public.practice_rooms r
                    join public.scenarios s on s.id = r.scenario_id
                    where r.id = :room_id
                    """
                ),
                {"room_id": room_id},
            ).scalar_one_or_none()
            return max_turns is not None and turn_count >= int(max_turns)
        return False

    @staticmethod
    def _complete_room(
        session: Session,
        user_id: UUID,
        room_id: UUID,
        practice_type: str,
        configuration_id: UUID | None,
    ) -> None:
        session.execute(
            text(
                """
                update public.practice_rooms
                set status = 'completed', ended_reason = 'completed',
                    completed_at = now(), updated_at = now()
                where id = :room_id and user_id = :user_id and status = 'in_progress'
                """
            ),
            {"room_id": room_id, "user_id": user_id},
        )
        if configuration_id is not None:
            session.execute(
                text(
                    """
                    update public.interview_configurations
                    set status = 'completed', completed_at = now(), updated_at = now()
                    where id = :configuration_id and user_id = :user_id
                    """
                ),
                {"configuration_id": configuration_id, "user_id": user_id},
            )
        result_id = session.execute(
            text(
                """
                insert into public.session_results
                    (room_id, user_id, result_status, interview_setup_snapshot)
                values (:room_id, :user_id, 'processing',
                        case when :is_interview then
                          jsonb_build_object(
                            'configuration_id', cast(:configuration_id as text)
                          )
                        else null end)
                returning id
                """
            ),
            {
                "room_id": room_id,
                "user_id": user_id,
                "is_interview": practice_type == "interview",
                "configuration_id": configuration_id,
            },
        ).scalar_one()
        _insert_job(
            session,
            user_id=user_id,
            job_type=JobType.SESSION_RESULT_GENERATION,
            target_id=result_id,
        )

    def retry(
        self,
        session: Session,
        item: ClaimedJob,
        code: str,
        next_attempt_at: datetime,
    ) -> None:
        _retry_target(
            session,
            "message_ai_processing",
            "processing_status",
            item,
            code,
            next_attempt_at,
        )

    def fail(self, session: Session, item: ClaimedJob, code: str) -> None:
        _fail_target(
            session,
            "message_ai_processing",
            "processing_status",
            item,
            code,
        )


class EmotionAdapter:
    job_type = JobType.EMOTION_ANALYSIS

    def claim(self, session: Session, job: Mapping[str, Any]) -> TargetClaim | None:
        target_id = _target_id(job, self.job_type)
        row = (
            session.execute(
                text(
                    """
                    select e.id, e.processing_token, m.content
                    from public.message_emotion_analysis e
                    join public.room_messages m on m.id = e.message_id
                    join public.practice_rooms r on r.id = m.room_id
                    where e.id = :target_id and e.processing_status = 'processing'
                      and r.user_id = :user_id
                    for update of e
                    """
                ),
                {"target_id": target_id, "user_id": job["user_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return TargetClaim(
            target_id,
            row["processing_token"],
            "provider_processing",
            {"text": row["content"]},
        )

    def complete(self, session: Session, item: ClaimedJob, output: object) -> bool:
        if not isinstance(output, EmotionAnalysis):
            raise TypeError("emotion output type mismatch")
        return (
            session.execute(
                text(
                    """
                    update public.message_emotion_analysis
                    set processing_status = 'succeeded', emotion_label = :label,
                        reasoning = :reasoning, error_code = null,
                        completed_at = now(), updated_at = now()
                    where id = :target_id and processing_token = :token
                      and processing_status = 'processing'
                    returning id
                    """
                ),
                {
                    "target_id": item.target_id,
                    "token": item.processing_token,
                    "label": output.label,
                    "reasoning": output.reasoning,
                },
            ).first()
            is not None
        )

    def retry(
        self,
        session: Session,
        item: ClaimedJob,
        code: str,
        next_attempt_at: datetime,
    ) -> None:
        _retry_target(
            session,
            "message_emotion_analysis",
            "processing_status",
            item,
            code,
            next_attempt_at,
        )

    def fail(self, session: Session, item: ClaimedJob, code: str) -> None:
        _fail_target(
            session,
            "message_emotion_analysis",
            "processing_status",
            item,
            code,
        )




class FeedbackAdapter:
    job_type = JobType.TURN_FEEDBACK

    def claim(self, session: Session, job: Mapping[str, Any]) -> TargetClaim | None:
        target_id = _target_id(job, self.job_type)
        row = (
            session.execute(
                text(
                    """
                    select f.id, f.processing_token, m.content, m.room_id,
                           m.sequence_no, r.practice_type, r.title, r.goal_snapshot,
                           p.name as persona_name, ps.role_key,
                           ctx.summary_text, ctx.summarized_through_message_id
                    from public.turn_feedback f
                    join public.room_messages m on m.id = f.message_id
                    join public.practice_rooms r on r.id = m.room_id
                    left join public.personas p on p.id = r.persona_id
                    left join public.persona_scenarios ps
                      on ps.persona_id = r.persona_id and ps.scenario_id = r.scenario_id
                    left join public.room_contexts ctx on ctx.room_id = r.id
                    where f.id = :target_id and f.analysis_status = 'processing'
                      and r.user_id = :user_id
                    for update of f
                    """
                ),
                {"target_id": target_id, "user_id": job["user_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        # 요약이 덮은 구간 이후는 전부 원문으로 보낸다. 고정 개수로 자르면 요약이
        # 아직 만들어지지 않은 짧은 대화에서 앞부분이 통째로 사라진다.
        preceding = list(
            session.execute(
                text(
                    """
                    select sequence_no, sender_type, content
                    from public.room_messages
                    where room_id = :room_id and sequence_no < :sequence_no
                      and (
                        cast(:through_message_id as uuid) is null
                        or sequence_no > coalesce((
                          select sequence_no from public.room_messages
                          where id = cast(:through_message_id as uuid)
                            and room_id = :room_id
                        ), 0)
                      )
                    order by sequence_no
                    """
                ),
                {
                    "room_id": row["room_id"],
                    "sequence_no": row["sequence_no"],
                    "through_message_id": row["summarized_through_message_id"],
                },
            ).mappings()
        )
        previous_persona_message = next(
            (
                message["content"]
                for message in reversed(preceding)
                if message["sender_type"] == "persona"
            ),
            None,
        )
        return TargetClaim(
            target_id,
            row["processing_token"],
            "provider_processing",
            {
                # 채점 대상은 이 문장 하나다. context 는 판단 배경일 뿐이다.
                "target_utterance": row["content"],
                "context": {
                    "practice_type": row["practice_type"],
                    "situation": row["title"],
                    "goal": row["goal_snapshot"],
                    "persona_name": row["persona_name"],
                    "relationship": row["role_key"],
                    "previous_persona_message": previous_persona_message,
                    "preceding_messages": [dict(message) for message in preceding],
                    "earlier_summary": row["summary_text"],
                },
            },
        )

    def complete(self, session: Session, item: ClaimedJob, output: object) -> bool:
        if not isinstance(output, GeneralFeedback):
            raise TypeError("feedback output type mismatch")
        locked = session.execute(
            text(
                """
                select id from public.turn_feedback
                where id = :target_id and processing_token = :token
                  and analysis_status = 'processing'
                for update
                """
            ),
            {"target_id": item.target_id, "token": item.processing_token},
        ).first()
        if locked is None:
            return False
        session.execute(
            text("delete from public.feedback_scores where feedback_id = :target_id"),
            {"target_id": item.target_id},
        )
        session.execute(
            text("delete from public.feedback_emotions where feedback_id = :target_id"),
            {"target_id": item.target_id},
        )
        for score in output.scores:
            session.execute(
                text(
                    """
                    insert into public.feedback_scores
                        (feedback_id, category, score, max_score, strength_text,
                         suggestion_text, original_expression, recommended_expression)
                    values (:feedback_id, :category, :score, 25, :strength,
                            :suggestion, :original_text, :recommended_text)
                    """
                ),
                {"feedback_id": item.target_id, **score.model_dump()},
            )
        for sort_order, emotion in enumerate(output.emotions, 1):
            session.execute(
                text(
                    """
                    insert into public.feedback_emotions
                        (feedback_id, emotion_label, percentage, impression_text,
                         sort_order, analysis_source, evidence_text)
                    values (:feedback_id, :label, :percentage, :impression,
                            :sort_order, 'text', :evidence)
                    """
                ),
                {
                    "feedback_id": item.target_id,
                    "sort_order": sort_order,
                    **emotion.model_dump(),
                },
            )
        categories = {score.category for score in output.scores}
        complete = categories == {
            "honorifics",
            "courtesy",
            "context_fit",
            "naturalness",
        }
        overall = sum(score.score for score in output.scores) if complete else None
        session.execute(
            text(
                """
                update public.turn_feedback
                set analysis_status = :status, overall_score = :overall,
                    summary = :summary, error_code = null, updated_at = now()
                where id = :target_id and processing_token = :token
                """
            ),
            {
                "target_id": item.target_id,
                "token": item.processing_token,
                "status": "ready" if complete else "partial",
                "overall": overall,
                "summary": output.summary,
            },
        )
        return True

    def retry(
        self,
        session: Session,
        item: ClaimedJob,
        code: str,
        next_attempt_at: datetime,
    ) -> None:
        _retry_target(
            session,
            "turn_feedback",
            "analysis_status",
            item,
            code,
            next_attempt_at,
        )

    def fail(self, session: Session, item: ClaimedJob, code: str) -> None:
        _fail_target(session, "turn_feedback", "analysis_status", item, code)


class GoalProgressAdapter:
    """시나리오 성공 조건의 달성 여부를 판정해 조기 종료 후보를 표시한다.

    방을 직접 완료시키지 않는다. 판정은 답장보다 늦게 도착하므로 여기서 방을
    끝내면 그 틈에 답변을 보낸 사용자가 오류를 받는다. 표시만 남기고 최종
    결정은 사용자가 한다.
    """

    job_type = JobType.SCENARIO_GOAL_PROGRESS

    def claim(self, session: Session, job: Mapping[str, Any]) -> TargetClaim | None:
        target_id = _target_id(job, self.job_type)
        row = (
            session.execute(
                text(
                    """
                    select e.id, e.processing_token, e.room_id, e.turn_no,
                           r.title, r.goal_snapshot, r.scenario_id, ps.role_key
                    from public.room_goal_evaluations e
                    join public.practice_rooms r on r.id = e.room_id
                    left join public.persona_scenarios ps
                      on ps.persona_id = r.persona_id and ps.scenario_id = r.scenario_id
                    where e.id = :target_id and e.evaluation_status = 'processing'
                      and r.user_id = :user_id
                    for update of e
                    """
                ),
                {"target_id": target_id, "user_id": job["user_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        conditions = list(
            session.execute(
                text(
                    """
                    select c.condition_key, c.description, c.is_required,
                           coalesce(p.achieved, false) as already_achieved
                    from public.scenario_success_conditions c
                    left join public.room_success_condition_progress p
                      on p.condition_id = c.id and p.room_id = :room_id
                    where c.scenario_id = :scenario_id
                    order by c.sort_order
                    """
                ),
                {"room_id": row["room_id"], "scenario_id": row["scenario_id"]},
            ).mappings()
        )
        if not conditions:
            return None
        messages = list(
            session.execute(
                text(
                    """
                    select sequence_no, sender_type, content
                    from public.room_messages
                    where room_id = :room_id
                    order by sequence_no
                    """
                ),
                {"room_id": row["room_id"]},
            ).mappings()
        )
        return TargetClaim(
            target_id,
            row["processing_token"],
            "provider_processing",
            {
                "goal": row["goal_snapshot"],
                "situation": row["title"],
                "relationship": row["role_key"],
                "conditions": [
                    {
                        "condition_key": condition["condition_key"],
                        "description": condition["description"],
                    }
                    for condition in conditions
                ],
                "already_achieved": [
                    condition["condition_key"]
                    for condition in conditions
                    if condition["already_achieved"]
                ],
                "messages": [dict(message) for message in messages],
            },
        )

    def complete(self, session: Session, item: ClaimedJob, output: object) -> bool:
        if not isinstance(output, ScenarioGoalProgress):
            raise TypeError("goal progress output type mismatch")
        locked = (
            session.execute(
                text(
                    """
                    select e.room_id, r.scenario_id
                    from public.room_goal_evaluations e
                    join public.practice_rooms r on r.id = e.room_id
                    where e.id = :target_id and e.processing_token = :token
                      and e.evaluation_status = 'processing'
                    for update of e
                    """
                ),
                {"target_id": item.target_id, "token": item.processing_token},
            )
            .mappings()
            .one_or_none()
        )
        if locked is None:
            return False
        room_id = locked["room_id"]
        for condition in output.conditions:
            if not condition.achieved:
                # 달성은 단조롭다. 워커가 동시에 돌아 늦은 턴의 판정이 먼저
                # 끝날 수 있으므로 false 로 되돌리는 갱신은 하지 않는다.
                continue
            session.execute(
                text(
                    """
                    insert into public.room_success_condition_progress
                        (room_id, condition_id, achieved, evidence_message_id,
                         reasoning, evaluated_at)
                    select :room_id, c.id, true, m.id, :reasoning, now()
                    from public.scenario_success_conditions c
                    left join public.room_messages m
                      on m.room_id = :room_id
                     and m.sequence_no = :evidence_sequence_no
                    where c.scenario_id = :scenario_id
                      and c.condition_key = :condition_key
                    on conflict (room_id, condition_id) do update
                    set achieved = true,
                        evidence_message_id = coalesce(
                            public.room_success_condition_progress.evidence_message_id,
                            excluded.evidence_message_id
                        ),
                        reasoning = coalesce(
                            public.room_success_condition_progress.reasoning,
                            excluded.reasoning
                        ),
                        evaluated_at = now()
                    where not public.room_success_condition_progress.achieved
                    """
                ),
                {
                    "room_id": room_id,
                    "scenario_id": locked["scenario_id"],
                    "condition_key": condition.condition_key,
                    "reasoning": condition.reasoning,
                    "evidence_sequence_no": condition.evidence_sequence_no,
                },
            )
        remaining_required = session.execute(
            text(
                """
                select count(*)
                from public.scenario_success_conditions c
                where c.scenario_id = :scenario_id and c.is_required
                  and not exists (
                    select 1 from public.room_success_condition_progress p
                    where p.room_id = :room_id and p.condition_id = c.id and p.achieved
                  )
                """
            ),
            {"room_id": room_id, "scenario_id": locked["scenario_id"]},
        ).scalar_one()
        all_required_met = int(remaining_required) == 0
        if all_required_met:
            # ended_reason 을 'awaiting_user_end' 로 두면 메시지 전송이 서버에서
            # 막힌다. 시나리오의 조기 종료는 강제가 아니라 제안이므로 다른 값을 쓴다.
            session.execute(
                text(
                    """
                    update public.practice_rooms
                    set ended_reason = 'goal_achieved', updated_at = now()
                    where id = :room_id and status = 'in_progress'
                      and ended_reason is null and goal_prompt_dismissed_at is null
                    """
                ),
                {"room_id": room_id},
            )
        session.execute(
            text(
                """
                update public.room_goal_evaluations
                set evaluation_status = 'succeeded', achieved = :achieved,
                    error_code = null, evaluated_at = now(), updated_at = now()
                where id = :target_id and processing_token = :token
                """
            ),
            {
                "target_id": item.target_id,
                "token": item.processing_token,
                "achieved": all_required_met,
            },
        )
        return True

    def retry(
        self,
        session: Session,
        item: ClaimedJob,
        code: str,
        next_attempt_at: datetime,
    ) -> None:
        _retry_target(
            session,
            "room_goal_evaluations",
            "evaluation_status",
            item,
            code,
            next_attempt_at,
        )

    def fail(self, session: Session, item: ClaimedJob, code: str) -> None:
        # 판정이 실패해도 대화는 그대로 굴러가고 max_turns 로 자연 종료된다.
        _fail_target(session, "room_goal_evaluations", "evaluation_status", item, code)


class TTSAdapter:
    job_type = JobType.TTS_GENERATION

    def __init__(self, storage: StorageObjectStore) -> None:
        self._storage = storage

    def claim(self, session: Session, job: Mapping[str, Any]) -> TargetClaim | None:
        target_id = _target_id(job, self.job_type)
        session.execute(
            text(
                "delete from public.tts_stream_chunks "
                "where expires_at <= now() or message_audio_id = :target_id"
            ),
            {"target_id": target_id},
        )
        row = (
            session.execute(
                text(
                    """
                    select a.id, a.processing_token, a.storage_path, m.content,
                           m.persona_emotion, p.prompt_bundle_key
                    from public.message_audio a
                    join public.room_messages m on m.id = a.message_id
                    join public.practice_rooms r on r.id = m.room_id
                    left join public.personas p on p.id = r.persona_id
                    where a.id = :target_id and a.generation_status = 'processing'
                      and a.is_current and r.user_id = :user_id
                    for update of a
                    """
                ),
                {"target_id": target_id, "user_id": job["user_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        payload: dict[str, Any] = {
            "text": row["content"],
            "emotion": row["persona_emotion"] or "neutral",
            "storage_path": row["storage_path"],
        }
        # 음성은 페르소나 번들이 정한다. 번들이 없으면 executor 기본값을 쓴다.
        if row["prompt_bundle_key"]:
            payload["prompt_bundle"] = row["prompt_bundle_key"]
        return TargetClaim(
            target_id,
            row["processing_token"],
            "provider_processing",
            payload,
        )

    def complete(self, session: Session, item: ClaimedJob, output: object) -> bool:
        if not isinstance(output, TTSOutput):
            raise TypeError("TTS output type mismatch")
        try:
            self._storage.upload(
                "message-audio", output.storage_path, output.wav, "audio/wav"
            )
        except RuntimeError as error:
            raise AIProviderError("STORAGE_UNAVAILABLE", retryable=True) from error
        updated = session.execute(
            text(
                """
                update public.message_audio
                set generation_status = 'ready', duration_ms = :duration_ms,
                    error_code = null, completed_at = now(), updated_at = now()
                where id = :target_id and processing_token = :token
                  and generation_status = 'processing' and is_current
                returning id
                """
            ),
            {
                "target_id": item.target_id,
                "token": item.processing_token,
                "duration_ms": _wav_duration_ms(output.wav),
            },
        ).first()
        if updated is None:
            self._storage.delete("message-audio", output.storage_path)
            return False
        return True

    def retry(
        self,
        session: Session,
        item: ClaimedJob,
        code: str,
        next_attempt_at: datetime,
    ) -> None:
        _retry_target(
            session,
            "message_audio",
            "generation_status",
            item,
            code,
            next_attempt_at,
        )

    def fail(self, session: Session, item: ClaimedJob, code: str) -> None:
        _fail_target(session, "message_audio", "generation_status", item, code)


class DocumentAnalysisAdapter:
    job_type = JobType.INTERVIEW_DOCUMENT_ANALYSIS

    def claim(self, session: Session, job: Mapping[str, Any]) -> TargetClaim | None:
        target_id = _target_id(job, self.job_type)
        row = (
            session.execute(
                text(
                    """
                    select a.id, a.processing_token, a.document_id, d.version_no,
                           d.document_type, coalesce(d.extracted_content->>'text', '') as text
                    from public.interview_document_analyses a
                    join public.interview_documents d on d.id = a.document_id
                    where a.id = :target_id and a.processing_status = 'processing'
                      and a.user_id = :user_id and d.user_id = :user_id
                      and d.is_current and d.deleted_at is null
                    for update of a, d
                    """
                ),
                {"target_id": target_id, "user_id": job["user_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if row is None or not str(row["text"]).strip():
            return None
        return TargetClaim(
            target_id,
            row["processing_token"],
            "extracting_text",
            {
                "document_id": str(row["document_id"]),
                "document_version": row["version_no"],
                "document_type": row["document_type"],
                "extracted_text": row["text"],
            },
        )

    def complete(self, session: Session, item: ClaimedJob, output: object) -> bool:
        if not isinstance(output, DocumentAnalysisOutput):
            raise TypeError("document analysis output type mismatch")
        document_id = UUID(str(item.payload["document_id"]))
        version = int(item.payload["document_version"])
        updated = session.execute(
            text(
                """
                update public.interview_document_analyses a
                set processing_status = 'succeeded', extracted_data = cast(:sections as jsonb),
                    citation_evidence = cast(:citations as jsonb), error_code = null,
                    completed_at = now(), updated_at = now()
                from public.interview_documents d
                where a.id = :target_id and a.processing_token = :token
                  and a.processing_status = 'processing' and d.id = a.document_id
                  and d.id = :document_id and d.version_no = :version
                  and d.is_current and d.deleted_at is null
                returning a.id
                """
            ),
            {
                "target_id": item.target_id,
                "token": item.processing_token,
                "document_id": document_id,
                "version": version,
                "sections": output.analysis.sections.model_dump_json(),
                "citations": json.dumps(
                    [citation.model_dump() for citation in output.analysis.citations],
                    ensure_ascii=False,
                ),
            },
        ).first()
        if updated is None:
            return False
        session.execute(
            text(
                "delete from public.document_chunks "
                "where document_id = :document_id and document_version = :version"
            ),
            {"document_id": document_id, "version": version},
        )
        for index, section, content, embedding in output.chunks:
            session.execute(
                text(
                    """
                    insert into public.document_chunks
                        (user_id, document_id, analysis_id, document_version,
                         chunk_index, section, content, token_count, source_ref, embedding)
                    values (:user_id, :document_id, :analysis_id, :version,
                            :chunk_index, :section, :content, :token_count,
                            cast(:source_ref as jsonb), cast(:embedding as vector))
                    """
                ),
                {
                    "user_id": item.user_id,
                    "document_id": document_id,
                    "analysis_id": item.target_id,
                    "version": version,
                    "chunk_index": index,
                    "section": section,
                    "content": content,
                    "token_count": len(content.split()),
                    "source_ref": json.dumps(
                        {"section": section, "chunk_index": index}
                    ),
                    "embedding": "[" + ",".join(str(value) for value in embedding) + "]",
                },
            )
        session.execute(
            text(
                """
                update public.interview_documents
                set processing_status = 'ready', analysis_status = 'succeeded',
                    processed_at = now(), updated_at = now()
                where id = :document_id and version_no = :version
                  and is_current and deleted_at is null
                """
            ),
            {"document_id": document_id, "version": version},
        )
        return True

    def retry(
        self,
        session: Session,
        item: ClaimedJob,
        code: str,
        next_attempt_at: datetime,
    ) -> None:
        _retry_target(
            session,
            "interview_document_analyses",
            "processing_status",
            item,
            code,
            next_attempt_at,
        )

    def fail(self, session: Session, item: ClaimedJob, code: str) -> None:
        _fail_target(
            session,
            "interview_document_analyses",
            "processing_status",
            item,
            code,
        )


class ConfigurationAdapter:
    job_type = JobType.INTERVIEW_CONFIGURATION_GENERATION

    def claim(self, session: Session, job: Mapping[str, Any]) -> TargetClaim | None:
        target_id = _target_id(job, self.job_type)
        row = (
            session.execute(
                text(
                    """
                    select c.id, c.processing_token, c.question_count,
                           c.document_version_snapshot, c.analysis_ids,
                           s.desired_role
                    from public.interview_configurations c
                    join public.interview_setups s on s.id = c.setup_id
                    where c.id = :target_id and c.status = 'processing'
                      and c.user_id = :user_id and c.invalidated_at is null
                    for update of c
                    """
                ),
                {"target_id": target_id, "user_id": job["user_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        documents = list(
            session.execute(
                text(
                    """
                    select d.id, d.version_no
                    from public.interview_document_analyses a
                    join public.interview_documents d on d.id = a.document_id
                    where a.id = any(:analysis_ids) and a.user_id = :user_id
                      and a.processing_status = 'succeeded'
                      and d.user_id = :user_id and d.is_current and d.deleted_at is null
                    """
                ),
                {"analysis_ids": row["analysis_ids"], "user_id": job["user_id"]},
            ).mappings()
        )
        if len(documents) != len(row["analysis_ids"]):
            return None
        snapshot = dict(row["document_version_snapshot"] or {})
        return TargetClaim(
            target_id,
            row["processing_token"],
            "retrieving_evidence",
            {
                "conditions": snapshot.get("conditions", {}),
                "desired_role": row["desired_role"],
                "question_count": row["question_count"],
                "document_versions": {
                    str(document["id"]): document["version_no"] for document in documents
                },
            },
        )

    def complete(self, session: Session, item: ClaimedJob, output: object) -> bool:
        if not isinstance(output, ConfigurationOutput):
            raise TypeError("configuration output type mismatch")
        locked = session.execute(
            text(
                """
                select id from public.interview_configurations
                where id = :target_id and processing_token = :token
                  and status = 'processing' and invalidated_at is null
                for update
                """
            ),
            {"target_id": item.target_id, "token": item.processing_token},
        ).first()
        if locked is None:
            return False
        session.execute(
            text("delete from public.interview_questions where configuration_id = :id"),
            {"id": item.target_id},
        )
        for question in output.questions.questions:
            session.execute(
                text(
                    """
                    insert into public.interview_questions
                        (configuration_id, sequence_no, question_text, question_type,
                         is_required, source_evidence, evaluation_focus)
                    values (:configuration_id, :sequence, :question_text, :question_type,
                            :required, cast(:source_refs as jsonb),
                            cast(:evaluation_focus as jsonb))
                    """
                ),
                {
                    "configuration_id": item.target_id,
                    "sequence": question.sequence,
                    "question_text": question.text,
                    "question_type": question.type,
                    "required": question.required,
                    "source_refs": json.dumps(
                        [source.model_dump() for source in question.source_refs],
                        ensure_ascii=False,
                        default=str,
                    ),
                    "evaluation_focus": json.dumps(question.evaluation_focus),
                },
            )
        session.execute(
            text(
                """
                update public.interview_configurations
                set status = 'ready', error_code = null, error_message = null,
                    completed_at = now(), updated_at = now()
                where id = :target_id and processing_token = :token
                """
            ),
            {"target_id": item.target_id, "token": item.processing_token},
        )
        return True

    def retry(
        self,
        session: Session,
        item: ClaimedJob,
        code: str,
        next_attempt_at: datetime,
    ) -> None:
        _retry_target(
            session,
            "interview_configurations",
            "status",
            item,
            code,
            next_attempt_at,
        )

    def fail(self, session: Session, item: ClaimedJob, code: str) -> None:
        _fail_target(
            session,
            "interview_configurations",
            "status",
            item,
            code,
        )


class SessionResultAdapter:
    job_type = JobType.SESSION_RESULT_GENERATION

    def claim(self, session: Session, job: Mapping[str, Any]) -> TargetClaim | None:
        target_id = _target_id(job, self.job_type)
        row = (
            session.execute(
                text(
                    """
                    select s.id, s.room_id, r.practice_type, r.title,
                           r.interview_configuration_id, r.goal_snapshot,
                           r.scenario_id, p.name as persona_name, ps.role_key
                    from public.session_results s
                    join public.practice_rooms r on r.id = s.room_id
                    left join public.personas p on p.id = r.persona_id
                    left join public.persona_scenarios ps
                      on ps.persona_id = r.persona_id and ps.scenario_id = r.scenario_id
                    where s.id = :target_id and s.result_status = 'processing'
                      and s.user_id = :user_id and r.user_id = :user_id
                    for update of s
                    """
                ),
                {"target_id": target_id, "user_id": job["user_id"]},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        average_feedback_score = session.execute(
            text(
                """
                select coalesce(avg(f.overall_score), 0)
                from public.room_messages m
                join public.turn_feedback f on f.message_id = m.id
                  and f.analysis_status = 'ready'
                where m.room_id = :room_id
                """
            ),
            {"room_id": row["room_id"]},
        ).scalar_one()
        messages = list(
            session.execute(
                text(
                    """
                    select m.sequence_no, m.sender_type, m.content,
                           q.question_text, q.evaluation_focus, q.source_evidence
                    from public.room_messages m
                    left join public.interview_answers a on a.message_id = m.id
                    left join public.interview_questions q on q.id = a.question_id
                    where m.room_id = :room_id
                    order by m.sequence_no, m.id
                    """
                ),
                {"room_id": row["room_id"]},
            ).mappings()
        )
        # 시나리오가 성공으로 규정한 조건. 대화가 끝난 지금이 충족 여부를 판정할
        # 시점이라, 판정에 쓸 목록을 함께 싣는다.
        success_conditions = list(
            session.execute(
                text(
                    """
                    select sc.condition_key, sc.description, sc.is_required
                    from public.scenario_success_conditions sc
                    where sc.scenario_id = :scenario_id
                    order by sc.sort_order, sc.condition_key
                    """
                ),
                {"scenario_id": row["scenario_id"]},
            ).mappings()
        )
        # 턴별 채점은 평균 한 숫자로 뭉개면 어느 항목이 반복해서 약했는지 알 수 없다.
        turn_scores = list(
            session.execute(
                text(
                    """
                    select m.sequence_no, fs.category, fs.score, fs.max_score,
                           fs.suggestion_text
                    from public.room_messages m
                    join public.turn_feedback f on f.message_id = m.id
                      and f.analysis_status = 'ready'
                    join public.feedback_scores fs on fs.feedback_id = f.id
                    where m.room_id = :room_id
                    order by m.sequence_no, fs.category
                    """
                ),
                {"room_id": row["room_id"]},
            ).mappings()
        )
        token = UUID(int=0)
        return TargetClaim(
            target_id,
            token,
            "aggregating_evidence",
            {
                "room_id": str(row["room_id"]),
                "title": row["title"],
                "practice_type": row["practice_type"],
                "is_interview": row["practice_type"] == "interview",
                "configuration_id": str(row["interview_configuration_id"])
                if row["interview_configuration_id"]
                else None,
                "goal": row["goal_snapshot"],
                "persona_name": row["persona_name"],
                "relationship": row["role_key"],
                "success_conditions": [dict(condition) for condition in success_conditions],
                "messages": [dict(message) for message in messages],
                "turn_scores": [dict(score) for score in turn_scores],
                "general_overall_score": int(
                    Decimal(average_feedback_score or 0).quantize(Decimal("1"))
                ),
            },
        )

    def complete(self, session: Session, item: ClaimedJob, output: object) -> bool:
        if not isinstance(output, FinalSessionOutput):
            raise TypeError("session result output type mismatch")
        locked = session.execute(
            text(
                """
                select id from public.session_results
                where id = :target_id and user_id = :user_id
                  and result_status = 'processing'
                for update
                """
            ),
            {"target_id": item.target_id, "user_id": item.user_id},
        ).first()
        if locked is None:
            return False
        session.execute(
            text("delete from public.result_items where result_id = :result_id"),
            {"result_id": item.target_id},
        )
        session.execute(
            text(
                "delete from public.interview_evaluation_scores "
                "where result_id = :result_id"
            ),
            {"result_id": item.target_id},
        )
        for order, result_item in enumerate(output.result.items, 1):
            session.execute(
                text(
                    """
                    insert into public.result_items
                        (result_id, item_type, category, title, original_expression,
                         recommended_expression, explanation, evidence_text,
                         source_document_id, sort_order)
                    values (:result_id, :item_type, :category, :title,
                            :original_expression, :recommended_expression, :explanation,
                            :evidence, :source_document_id, :sort_order)
                    """
                ),
                {
                    "result_id": item.target_id,
                    "sort_order": order,
                    "source_document_id": result_item.source_document_id,
                    **result_item.model_dump(exclude={"source_document_id"}),
                },
            )
        evaluation: InterviewEvaluation | None = output.interview_evaluation
        if evaluation is not None:
            for score in evaluation.scores:
                session.execute(
                    text(
                        """
                        insert into public.interview_evaluation_scores
                            (result_id, category, score, strength_text,
                             suggestion_text, evidence_text)
                        values (:result_id, :category, :score, :strength,
                                :suggestion, :evidence)
                        """
                    ),
                    {"result_id": item.target_id, **score.model_dump()},
                )
            status = evaluation.status
            overall = evaluation.overall_score
            missing = list(evaluation.missing_categories)
        else:
            status = "succeeded"
            overall = item.payload.get("general_overall_score")
            missing = []
        session.execute(
            text(
                """
                update public.session_results
                set result_status = :status, overall_score = :overall,
                    summary = :summary, missing_categories = :missing,
                    updated_at = now()
                where id = :result_id and user_id = :user_id
                  and result_status = 'processing'
                """
            ),
            {
                "result_id": item.target_id,
                "user_id": item.user_id,
                "status": status,
                "overall": overall,
                "summary": output.result.summary,
                "missing": missing,
            },
        )
        return True

    def retry(
        self,
        session: Session,
        item: ClaimedJob,
        code: str,
        next_attempt_at: datetime,
    ) -> None:
        del session, item, code, next_attempt_at

    def fail(self, session: Session, item: ClaimedJob, code: str) -> None:
        session.execute(
            text(
                """
                update public.session_results
                set result_status = 'failed', overall_score = null,
                    missing_categories = case
                      when interview_setup_snapshot is null then missing_categories
                      else array[
                        'question_understanding_fit', 'answer_structure',
                        'specificity_evidence', 'job_fit_problem_solving',
                        'delivery_attitude'
                      ]::text[]
                    end,
                    updated_at = now()
                where id = :target_id and user_id = :user_id
                  and result_status = 'processing'
                """
            ),
            {"target_id": item.target_id, "user_id": item.user_id},
        )


def _token_guarded_targets() -> set[tuple[str, str]]:
    """processing_token 으로 잠글 수 있는 (테이블, 상태컬럼) 조합.

    TARGET_STATE 에서 파생한다. 목록을 따로 두면 job 을 추가할 때 한쪽만
    고쳐서, 재시도와 실패 처리만 조용히 동작하지 않게 된다.
    """
    return {
        (table_name, status_column)
        for table_name, status_column, has_token in TARGET_STATE.values()
        if has_token
    }


def _retry_target(
    session: Session,
    table_name: str,
    status_column: str,
    item: ClaimedJob,
    code: str,
    next_attempt_at: datetime,
) -> None:
    allowed = _token_guarded_targets()
    if (table_name, status_column) not in allowed:
        raise ValueError("unsupported retry target")
    session.execute(
        text(
            f"""
            update public.{table_name}
            set error_code = :code, next_attempt_at = :next_attempt_at,
                updated_at = now()
            where id = :target_id and processing_token = :token
              and {status_column} = 'processing'
            """
        ),
        {
            "target_id": item.target_id,
            "token": item.processing_token,
            "code": code,
            "next_attempt_at": next_attempt_at,
        },
    )


def _fail_target(
    session: Session,
    table_name: str,
    status_column: str,
    item: ClaimedJob,
    code: str,
) -> None:
    allowed = _token_guarded_targets()
    if (table_name, status_column) not in allowed:
        raise ValueError("unsupported failure target")
    completed_assignment = (
        ""
        if table_name in {"turn_feedback", "room_goal_evaluations"}
        else "completed_at = now(),"
    )
    session.execute(
        text(
            f"""
            update public.{table_name}
            set {status_column} = 'failed', error_code = :code,
                {completed_assignment} updated_at = now()
            where id = :target_id and processing_token = :token
              and {status_column} = 'processing'
            """
        ),
        {
            "target_id": item.target_id,
            "token": item.processing_token,
            "code": code,
        },
    )


def _wav_duration_ms(wav: bytes) -> int:
    if len(wav) < 44:
        return 0
    byte_rate = int.from_bytes(wav[28:32], "little")
    data_size = int.from_bytes(wav[40:44], "little")
    return round(data_size / byte_rate * 1000) if byte_rate else 0
