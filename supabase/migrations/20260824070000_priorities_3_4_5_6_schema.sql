begin;

-- Priority 3: versioned interview configurations, ordered questions, and answer attempts.
create table if not exists public.interview_configurations (
  id uuid primary key default gen_random_uuid(),
  setup_id uuid not null references public.interview_setups(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  version_no integer not null check (version_no > 0),
  status text not null default 'processing'
    check (status in ('processing', 'ready', 'in_progress', 'completed', 'failed', 'invalidated')),
  idempotency_key uuid not null,
  document_version_snapshot jsonb not null default '{}'::jsonb,
  analysis_ids uuid[] not null default '{}',
  question_count smallint not null default 0 check (question_count between 0 and 10),
  processing_token uuid not null default gen_random_uuid(),
  deadline_at timestamptz,
  next_attempt_at timestamptz,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  invalidated_at timestamptz,
  updated_at timestamptz not null default now(),
  unique (setup_id, version_no),
  unique (setup_id, idempotency_key),
  check (status not in ('ready', 'in_progress', 'completed') or question_count between 1 and 10),
  check (status <> 'completed' or completed_at is not null),
  check (status <> 'invalidated' or invalidated_at is not null)
);

create unique index if not exists interview_configurations_one_active_idx
  on public.interview_configurations (setup_id)
  where status in ('processing', 'ready', 'in_progress');

create table if not exists public.interview_questions (
  id uuid primary key default gen_random_uuid(),
  configuration_id uuid not null references public.interview_configurations(id) on delete cascade,
  sequence_no smallint not null check (sequence_no between 1 and 10),
  question_text text not null check (btrim(question_text) <> ''),
  question_type text not null default 'required',
  is_required boolean not null default true,
  source_evidence jsonb not null default '[]'::jsonb,
  evaluation_focus jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (configuration_id, sequence_no)
);

create table if not exists public.interview_answers (
  id uuid primary key default gen_random_uuid(),
  question_id uuid not null references public.interview_questions(id) on delete cascade,
  room_id uuid not null references public.practice_rooms(id) on delete cascade,
  message_id uuid not null unique references public.room_messages(id) on delete cascade,
  answer_attempt_no integer not null default 1 check (answer_attempt_no > 0),
  is_current boolean not null default true,
  submitted_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (question_id, answer_attempt_no)
);

create unique index if not exists interview_answers_one_current_idx
  on public.interview_answers (question_id) where is_current;
create index if not exists interview_questions_configuration_sequence_idx
  on public.interview_questions (configuration_id, sequence_no);
create index if not exists interview_answers_room_submitted_idx
  on public.interview_answers (room_id, submitted_at);

create or replace function public.synchronize_interview_question_count()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  target_configuration_id uuid;
begin
  target_configuration_id := coalesce(new.configuration_id, old.configuration_id);
  update public.interview_configurations
  set question_count = (
        select count(*) from public.interview_questions q
        where q.configuration_id = target_configuration_id
      ),
      updated_at = now()
  where id = target_configuration_id;
  return coalesce(new, old);
end;
$$;

drop trigger if exists synchronize_interview_question_count_trigger on public.interview_questions;
create trigger synchronize_interview_question_count_trigger
after insert or delete or update of configuration_id on public.interview_questions
for each row execute function public.synchronize_interview_question_count();

alter table public.practice_rooms
  add column if not exists interview_configuration_id uuid
    references public.interview_configurations(id) on delete restrict;

create or replace function public.validate_interview_answer_message()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if not exists (
    select 1
    from public.room_messages m
    where m.id = new.message_id
      and m.room_id = new.room_id
      and m.sender_type = 'user'
  ) then
    raise exception 'interview answer must reference a user message in the same room';
  end if;
  if not exists (
    select 1
    from public.interview_questions q
    join public.interview_configurations c on c.id = q.configuration_id
    where q.id = new.question_id
      and c.id = (select r.interview_configuration_id from public.practice_rooms r where r.id = new.room_id)
  ) then
    raise exception 'interview answer question does not belong to the room configuration';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_interview_answer_message_trigger on public.interview_answers;
create trigger validate_interview_answer_message_trigger
before insert or update of question_id, room_id, message_id on public.interview_answers
for each row execute function public.validate_interview_answer_message();

alter table public.interview_configurations enable row level security;
alter table public.interview_questions enable row level security;
alter table public.interview_answers enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='interview_configurations' and policyname='interview_configurations_own_all') then
    create policy interview_configurations_own_all on public.interview_configurations for all to authenticated
      using (user_id = auth.uid()) with check (user_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='interview_questions' and policyname='interview_questions_own_configuration') then
    create policy interview_questions_own_configuration on public.interview_questions for all to authenticated
      using (exists (select 1 from public.interview_configurations c where c.id = configuration_id and c.user_id = auth.uid()))
      with check (exists (select 1 from public.interview_configurations c where c.id = configuration_id and c.user_id = auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='interview_answers' and policyname='interview_answers_own_configuration') then
    create policy interview_answers_own_configuration on public.interview_answers for all to authenticated
      using (exists (select 1 from public.practice_rooms r where r.id = room_id and r.user_id = auth.uid()))
      with check (exists (select 1 from public.practice_rooms r where r.id = room_id and r.user_id = auth.uid()));
  end if;
end $$;

-- Priority 4: score totals, user emotion limits, and onboarding completion contracts.
create or replace function public.recalculate_turn_feedback_overall_score()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  target_feedback_id uuid;
  category_count integer;
  total_score numeric;
begin
  target_feedback_id := coalesce(new.feedback_id, old.feedback_id);
  select count(distinct category), sum(score)
    into category_count, total_score
  from public.feedback_scores
  where feedback_id = target_feedback_id
    and category in ('honorifics', 'courtesy', 'context_fit', 'naturalness');

  update public.turn_feedback
  set overall_score = case when category_count = 4 then total_score else null end,
      updated_at = now()
  where id = target_feedback_id;
  return coalesce(new, old);
end;
$$;

drop trigger if exists feedback_scores_recalculate_overall_trigger on public.feedback_scores;
create trigger feedback_scores_recalculate_overall_trigger
after insert or update or delete on public.feedback_scores
for each row execute function public.recalculate_turn_feedback_overall_score();

alter table public.feedback_emotions
  add column if not exists analysis_source text not null default 'text',
  add column if not exists evidence_text text;

alter table public.feedback_emotions
  drop constraint if exists feedback_emotions_percentage_contract,
  add constraint feedback_emotions_percentage_contract
    check (percentage between 0 and 100 and sort_order between 1 and 3) not valid,
  drop constraint if exists feedback_emotions_analysis_source_contract,
  add constraint feedback_emotions_analysis_source_contract
    check (analysis_source in ('text', 'voice')) not valid,
  drop constraint if exists feedback_emotions_feedback_label_key,
  add constraint feedback_emotions_feedback_label_key unique (feedback_id, emotion_label);

create or replace function public.validate_feedback_emotion_limit()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if (
    select count(*)
    from public.feedback_emotions e
    where e.feedback_id = new.feedback_id and e.id <> new.id
  ) >= 3 then
    raise exception 'a feedback record can contain at most three emotions';
  end if;
  return new;
end;
$$;

drop trigger if exists validate_feedback_emotion_limit_trigger on public.feedback_emotions;
create trigger validate_feedback_emotion_limit_trigger
before insert or update of feedback_id on public.feedback_emotions
for each row execute function public.validate_feedback_emotion_limit();

create table if not exists public.consent_policies (
  id uuid primary key default gen_random_uuid(),
  consent_type text not null,
  policy_version text not null,
  is_required boolean not null default true,
  is_active boolean not null default true,
  effective_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique (consent_type, policy_version)
);

create unique index if not exists consent_policies_one_active_version_idx
  on public.consent_policies (consent_type) where is_active;

alter table public.consent_policies enable row level security;
do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='consent_policies' and policyname='consent_policies_authenticated_read') then
    create policy consent_policies_authenticated_read on public.consent_policies
      for select to authenticated using (true);
  end if;
end $$;

alter table public.profiles
  drop constraint if exists profiles_onboarding_fields_contract,
  add constraint profiles_onboarding_fields_contract check (
    not onboarding_completed or (
      display_name is not null and btrim(display_name) <> ''
      and birth_date is not null
      and gender is not null and btrim(gender) <> ''
      and native_language is not null and btrim(native_language) <> ''
      and display_language in ('ko', 'en')
    )
  ) not valid;

create or replace function public.validate_profile_onboarding_completion()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.onboarding_completed then
    if new.birth_date > current_date then
      raise exception 'birth_date <= current_date is required';
    end if;
    if not exists (select 1 from public.consent_policies p where p.is_active and p.is_required) then
      raise exception 'at least one active required consent policy is required';
    end if;
    if exists (
      select 1
      from public.consent_policies p
      where p.is_active and p.is_required
        and not exists (
          select 1 from public.user_consents c
          where c.user_id = new.id
            and c.consent_type = p.consent_type
            and c.policy_version = p.policy_version
            and c.accepted_at is not null
            and c.revoked_at is null
        )
    ) then
      raise exception 'all active required consent policies must be accepted';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists validate_profile_onboarding_completion_trigger on public.profiles;
create trigger validate_profile_onboarding_completion_trigger
before insert or update of onboarding_completed, display_name, birth_date, gender, native_language, display_language
on public.profiles
for each row execute function public.validate_profile_onboarding_completion();

-- Priority 5: one active room per product-defined combination.
create unique index if not exists practice_rooms_one_active_free_chat_idx
  on public.practice_rooms (user_id, persona_id)
  where practice_type = 'free_chat' and status = 'in_progress';
create unique index if not exists practice_rooms_one_active_scenario_idx
  on public.practice_rooms (user_id, persona_id, scenario_id)
  where practice_type = 'scenario' and status = 'in_progress';
create unique index if not exists practice_rooms_one_active_interview_idx
  on public.practice_rooms (user_id, interview_configuration_id)
  where practice_type = 'interview' and status = 'in_progress';

alter table public.practice_rooms
  drop constraint if exists practice_rooms_interview_configuration_contract,
  add constraint practice_rooms_interview_configuration_contract check (
    (practice_type = 'interview' and interview_configuration_id is not null)
    or (practice_type <> 'interview' and interview_configuration_id is null)
  ) not valid;

-- Priority 6: durable deletion claims and timeout/retry metadata. No worker is created here.
alter table public.storage_deletion_jobs
  add column if not exists max_attempts integer not null default 5,
  add column if not exists next_attempt_at timestamptz not null default now(),
  add column if not exists locked_at timestamptz,
  add column if not exists locked_by text,
  add column if not exists lock_expires_at timestamptz,
  add column if not exists error_code text,
  add column if not exists updated_at timestamptz not null default now();

alter table public.storage_deletion_jobs
  drop constraint if exists storage_deletion_jobs_retry_contract,
  add constraint storage_deletion_jobs_retry_contract check (
    max_attempts > 0 and attempt_count >= 0 and attempt_count <= max_attempts
    and ((locked_at is null and locked_by is null and lock_expires_at is null)
      or (locked_at is not null and locked_by is not null and lock_expires_at is not null))
  ) not valid;

create index if not exists storage_deletion_jobs_claim_idx
  on public.storage_deletion_jobs (deletion_status, next_attempt_at)
  where deletion_status in ('pending', 'failed');

create table if not exists public.processing_timeout_policies (
  job_type text primary key,
  timeout_seconds integer not null check (timeout_seconds > 0),
  max_attempts integer not null default 3 check (max_attempts > 0),
  is_active boolean not null default true,
  updated_at timestamptz not null default now()
);

insert into public.processing_timeout_policies (job_type, timeout_seconds, max_attempts)
values
  ('ai_response', 15, 3),
  ('emotion_analysis', 15, 3),
  ('feedback_analysis', 30, 3),
  ('tts_generation', 45, 3),
  ('interview_analysis', 60, 3),
  ('interview_configuration', 60, 3)
on conflict (job_type) do update
set timeout_seconds = excluded.timeout_seconds,
    max_attempts = excluded.max_attempts,
    updated_at = now();

alter table public.processing_timeout_policies enable row level security;

alter table public.message_ai_processing
  add column if not exists processing_token uuid not null default gen_random_uuid(),
  add column if not exists deadline_at timestamptz,
  add column if not exists next_attempt_at timestamptz;
alter table public.message_emotion_analysis
  add column if not exists processing_token uuid not null default gen_random_uuid(),
  add column if not exists deadline_at timestamptz,
  add column if not exists next_attempt_at timestamptz;
alter table public.message_audio
  add column if not exists processing_token uuid not null default gen_random_uuid(),
  add column if not exists deadline_at timestamptz,
  add column if not exists next_attempt_at timestamptz;
alter table public.turn_feedback
  add column if not exists processing_token uuid not null default gen_random_uuid(),
  add column if not exists deadline_at timestamptz,
  add column if not exists next_attempt_at timestamptz;
alter table public.interview_document_analyses
  add column if not exists processing_token uuid not null default gen_random_uuid(),
  add column if not exists deadline_at timestamptz,
  add column if not exists next_attempt_at timestamptz;

create index if not exists message_ai_processing_timeout_idx
  on public.message_ai_processing (processing_status, deadline_at)
  where processing_status = 'processing';
create index if not exists message_emotion_analysis_timeout_idx
  on public.message_emotion_analysis (processing_status, deadline_at)
  where processing_status = 'processing';
create index if not exists message_audio_timeout_idx
  on public.message_audio (generation_status, deadline_at)
  where generation_status = 'processing';
create index if not exists turn_feedback_timeout_idx
  on public.turn_feedback (analysis_status, deadline_at)
  where analysis_status = 'processing';
create index if not exists interview_document_analyses_timeout_idx
  on public.interview_document_analyses (processing_status, deadline_at)
  where processing_status = 'processing';
create index if not exists interview_configurations_timeout_idx
  on public.interview_configurations (status, deadline_at)
  where status = 'processing';

commit;
