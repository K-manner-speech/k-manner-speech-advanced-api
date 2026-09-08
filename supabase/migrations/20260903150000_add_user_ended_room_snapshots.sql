-- v1.1.0: 자유채팅·시나리오 사용자 종료와 결과 생성 범위를 보존한다.
-- 기존 ended_reason = 'completed' 데이터는 호환성을 위해 변환하지 않는다.

alter table public.practice_rooms
  add column if not exists evaluation_cutoff_message_id uuid,
  add column if not exists completed_turn_count integer;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.practice_rooms'::regclass
      and conname = 'practice_rooms_evaluation_cutoff_message_id_fkey'
  ) then
    alter table public.practice_rooms
      add constraint practice_rooms_evaluation_cutoff_message_id_fkey
      foreign key (evaluation_cutoff_message_id)
      references public.room_messages(id)
      on delete set null;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.practice_rooms'::regclass
      and conname = 'practice_rooms_completed_turn_count_check'
  ) then
    alter table public.practice_rooms
      add constraint practice_rooms_completed_turn_count_check
      check (completed_turn_count is null or completed_turn_count >= 0);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.practice_rooms'::regclass
      and conname = 'practice_rooms_completion_shape_check'
  ) then
    alter table public.practice_rooms
      add constraint practice_rooms_completion_shape_check
      check (
        (status <> 'completed' or (completed_at is not null and ended_reason is not null))
        and (status <> 'in_progress' or completed_at is null)
      );
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.practice_rooms'::regclass
      and conname = 'practice_rooms_ended_reason_check'
  ) then
    alter table public.practice_rooms
      add constraint practice_rooms_ended_reason_check
      check (
        ended_reason is null
        or ended_reason in (
          'completed',
          'awaiting_user_end',
          'goal_achieved',
          'max_turns_reached',
          'interview_completed',
          'user_ended'
        )
      );
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.practice_rooms'::regclass
      and conname = 'practice_rooms_user_ended_type_check'
  ) then
    alter table public.practice_rooms
      add constraint practice_rooms_user_ended_type_check
      check (ended_reason <> 'user_ended' or practice_type in ('free_chat', 'scenario'));
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.practice_rooms'::regclass
      and conname = 'practice_rooms_interview_completed_type_check'
  ) then
    alter table public.practice_rooms
      add constraint practice_rooms_interview_completed_type_check
      check (ended_reason <> 'interview_completed' or practice_type = 'interview');
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.practice_rooms'::regclass
      and conname = 'practice_rooms_awaiting_user_end_type_check'
  ) then
    alter table public.practice_rooms
      add constraint practice_rooms_awaiting_user_end_type_check
      check (
        ended_reason <> 'awaiting_user_end'
        or (practice_type = 'interview' and status = 'in_progress')
      );
  end if;
end
$$;

alter table public.session_results
  add column if not exists ended_reason text,
  add column if not exists completed_turn_count integer,
  add column if not exists evaluation_cutoff_message_id uuid,
  add column if not exists insufficient_data boolean not null default false;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.session_results'::regclass
      and conname = 'session_results_evaluation_cutoff_message_id_fkey'
  ) then
    alter table public.session_results
      add constraint session_results_evaluation_cutoff_message_id_fkey
      foreign key (evaluation_cutoff_message_id)
      references public.room_messages(id)
      on delete set null;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.session_results'::regclass
      and conname = 'session_results_completed_turn_count_check'
  ) then
    alter table public.session_results
      add constraint session_results_completed_turn_count_check
      check (completed_turn_count is null or completed_turn_count >= 0);
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.session_results'::regclass
      and conname = 'session_results_insufficient_data_score_check'
  ) then
    alter table public.session_results
      add constraint session_results_insufficient_data_score_check
      check (not insufficient_data or overall_score is null);
  end if;
end
$$;

alter table public.idempotency_records
  drop constraint if exists idempotency_records_action_scope_check;

alter table public.idempotency_records
  add constraint idempotency_records_action_scope_check
  check (
    action_scope = any (
      array[
        'room.create'::text,
        'room.end'::text,
        'room.delete'::text,
        'room_message.create'::text,
        'room_voice_message.create'::text,
        'message_response.retry'::text,
        'message_feedback.retry'::text,
        'message_emotion.retry'::text,
        'message_tts.retry'::text,
        'message_repeat.create'::text,
        'room_result.retry'::text,
        'result.delete'::text,
        'interview_setup.create'::text,
        'interview_document.create'::text,
        'interview_document.analyze'::text,
        'interview_document.replace'::text,
        'interview_document.delete'::text,
        'interview_configuration.generate'::text,
        'interview_configuration.regenerate'::text,
        'interview_practice_room.create'::text,
        'onboarding.complete'::text,
        'account.delete'::text
      ]
    )
  );

comment on column public.practice_rooms.evaluation_cutoff_message_id is
  '연습 종료 시 종합 피드백에 포함할 마지막 메시지 기준점입니다.';
comment on column public.practice_rooms.completed_turn_count is
  '연습 종료가 확정된 시점의 완료 턴 수 snapshot입니다.';
comment on column public.session_results.ended_reason is
  '결과 생성 시점에 복제한 대화방 종료 사유입니다.';
comment on column public.session_results.completed_turn_count is
  '결과 생성 시점에 복제한 완료 턴 수입니다.';
comment on column public.session_results.evaluation_cutoff_message_id is
  '이 결과가 평가한 마지막 메시지 기준점입니다.';
comment on column public.session_results.insufficient_data is
  '평가 가능한 발화가 부족하여 점수를 생성하지 않았는지 나타냅니다.';
