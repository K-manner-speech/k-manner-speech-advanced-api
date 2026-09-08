-- 시나리오 목표 조기 달성 판정 잡을 위한 스키마.
--
-- 큐 인프라는 잡마다 "상태 컬럼을 가진 대상 행"을 하나씩 요구한다.
-- room_success_condition_progress 는 조건당 1행이라 턴당 1번 도는 잡의
-- 대상이 될 수 없어서, turn_feedback 과 같은 모양의 턴 단위 테이블을 둔다.

create table if not exists public.room_goal_evaluations (
  id uuid primary key default gen_random_uuid(),
  room_id uuid not null references public.practice_rooms(id) on delete cascade,
  message_id uuid not null references public.room_messages(id) on delete cascade,
  turn_no integer not null,
  evaluation_status text not null default 'processing',
  processing_token uuid not null default gen_random_uuid(),
  attempt_count integer not null default 0,
  achieved boolean not null default false,
  error_code text,
  deadline_at timestamptz,
  next_attempt_at timestamptz,
  evaluated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (room_id, message_id)
);

create index if not exists room_goal_evaluations_room_idx
  on public.room_goal_evaluations (room_id, turn_no);

alter table public.processing_jobs
  add column if not exists room_goal_evaluation_id uuid
    references public.room_goal_evaluations(id) on delete cascade;

-- 이 행이 없으면 워커의 claim 쿼리가 processing_timeout_policies 와 조인할 때
-- 탈락해서, 잡이 에러도 로그도 없이 큐에 영원히 남는다.
insert into public.processing_timeout_policies (job_type, timeout_seconds, max_attempts)
values ('scenario_goal_progress', 20, 3)
on conflict (job_type) do update set
  timeout_seconds = excluded.timeout_seconds,
  max_attempts = excluded.max_attempts,
  is_active = true,
  updated_at = now();

-- "계속하기"를 누른 방은 남은 턴 동안 다시 판정하지 않는다.
alter table public.practice_rooms
  add column if not exists goal_prompt_dismissed_at timestamptz;

alter table public.room_goal_evaluations enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'room_goal_evaluations'
      and policyname = 'room_goal_evaluations_own_room'
  ) then
    create policy room_goal_evaluations_own_room on public.room_goal_evaluations
      for all to authenticated
      using (
        exists (
          select 1 from public.practice_rooms r
          where r.id = room_goal_evaluations.room_id and r.user_id = auth.uid()
        )
      )
      with check (
        exists (
          select 1 from public.practice_rooms r
          where r.id = room_goal_evaluations.room_id and r.user_id = auth.uid()
        )
      );
  end if;
end $$;

revoke all on public.room_goal_evaluations from anon, authenticated;

-- ---------------------------------------------------------------------------
-- 큐 재분배: 실시간(Gemini)과 채점(OpenAI)을 분리한다.
--
-- interactive_ai 는 지연에 민감한 TTS 와 180초짜리 종합 결과 잡을 함께 지고
-- 있었다. 워커 스레드가 큐당 2개뿐이라 종합 결과가 하나 돌면 남은 1개로
-- 음성·감정·피드백을 모두 처리해야 했다.
--
--   interactive_ai  → tts_generation, emotion_analysis            (실시간)
--   evaluation_ai   → turn_feedback, session_result_generation,
--                     scenario_goal_progress                       (채점)
-- ---------------------------------------------------------------------------

select pgmq.create('evaluation_ai');
select pgmq.create('evaluation_ai_dlq');

-- 발행과 소비가 같은 JOB_QUEUE_NAMES 를 보므로, 배포 시점에 옛 큐에 남아 있던
-- 채점 잡은 어느 워커도 집어가지 않고 붕 뜬다. 여기서 새 큐로 옮긴다.
do $$
declare
  pending record;
begin
  for pending in
    select q.msg_id, q.message
    from pgmq.q_interactive_ai q
    join public.processing_jobs j
      on j.id = (q.message ->> 'job_id')::uuid
    where j.job_type in ('turn_feedback', 'session_result_generation')
  loop
    perform pgmq.send('evaluation_ai', pending.message);
    perform pgmq.delete('interactive_ai', pending.msg_id);
  end loop;
end $$;

do $$
declare
  pending record;
begin
  for pending in
    select q.msg_id, q.message
    from pgmq.q_interactive_ai_dlq q
    join public.processing_jobs j
      on j.id = (q.message ->> 'job_id')::uuid
    where j.job_type in ('turn_feedback', 'session_result_generation')
  loop
    perform pgmq.send('evaluation_ai_dlq', pending.message);
    perform pgmq.delete('interactive_ai_dlq', pending.msg_id);
  end loop;
end $$;
