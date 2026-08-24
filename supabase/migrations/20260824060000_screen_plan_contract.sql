begin;

-- Shared status domains remain text for compatibility with the existing API.
alter table public.room_messages
  add column if not exists client_request_id uuid,
  add column if not exists reply_to_message_id uuid references public.room_messages(id) on delete cascade,
  add column if not exists processing_error text,
  add column if not exists updated_at timestamptz not null default now();

alter table public.room_messages
  drop constraint if exists room_messages_room_client_request_key,
  add constraint room_messages_room_client_request_key unique (room_id, client_request_id),
  drop constraint if exists room_messages_room_sequence_key,
  add constraint room_messages_room_sequence_key unique (room_id, sequence_no),
  drop constraint if exists room_messages_reply_to_key,
  add constraint room_messages_reply_to_key unique (reply_to_message_id);

create table if not exists public.message_ai_processing (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null unique references public.room_messages(id) on delete cascade,
  processing_status text not null default 'processing'
    check (processing_status in ('processing', 'succeeded', 'failed')),
  error_code text,
  error_message text,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  check ((processing_status = 'succeeded' and completed_at is not null) or processing_status <> 'succeeded')
);

create table if not exists public.message_emotion_analysis (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null unique references public.room_messages(id) on delete cascade,
  processing_status text not null default 'processing'
    check (processing_status in ('processing', 'succeeded', 'failed')),
  emotion_label text check (emotion_label in
    ('neutral', 'happy', 'sad', 'angry', 'curious', 'embarrassment')),
  reasoning text,
  error_code text,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  check (processing_status <> 'succeeded' or (emotion_label is not null and reasoning is not null))
);

alter table public.message_audio
  add column if not exists is_current boolean not null default true,
  add column if not exists replacement_for_id uuid references public.message_audio(id) on delete set null,
  add column if not exists error_code text,
  add column if not exists attempt_count integer not null default 0,
  add column if not exists completed_at timestamptz,
  add column if not exists updated_at timestamptz not null default now();

create unique index if not exists message_audio_one_current_type_idx
  on public.message_audio (message_id, audio_type) where is_current;

alter table public.turn_feedback
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists error_code text,
  add column if not exists attempt_count integer not null default 0;

alter table public.turn_feedback
  drop constraint if exists turn_feedback_message_key,
  add constraint turn_feedback_message_key unique (message_id),
  drop constraint if exists turn_feedback_overall_score_range,
  add constraint turn_feedback_overall_score_range
    check (overall_score is null or (overall_score between 0 and 100 and overall_score = trunc(overall_score))) not valid;

alter table public.feedback_scores
  drop constraint if exists feedback_scores_feedback_category_key,
  add constraint feedback_scores_feedback_category_key unique (feedback_id, category),
  drop constraint if exists feedback_scores_score_contract,
  add constraint feedback_scores_score_contract check (
    category in ('honorifics', 'courtesy', 'context_fit', 'naturalness')
    and score between 0 and 25
    and score = trunc(score)
    and max_score = 25
  ) not valid;

-- A scenario cannot start through the application RPC unless it has at least one required condition.
create table if not exists public.scenario_success_conditions (
  id uuid primary key default gen_random_uuid(),
  scenario_id uuid not null references public.scenarios(id) on delete cascade,
  condition_key text not null,
  description text not null,
  is_required boolean not null default true,
  sort_order integer not null default 0,
  created_at timestamptz not null default now(),
  unique (scenario_id, condition_key)
);

create table if not exists public.room_success_condition_progress (
  id uuid primary key default gen_random_uuid(),
  room_id uuid not null references public.practice_rooms(id) on delete cascade,
  condition_id uuid not null references public.scenario_success_conditions(id) on delete restrict,
  achieved boolean not null default false,
  evidence_message_id uuid references public.room_messages(id) on delete set null,
  reasoning text,
  evaluated_at timestamptz,
  unique (room_id, condition_id)
);

alter table public.practice_rooms
  add column if not exists ended_reason text,
  add column if not exists last_confirmed_turn_at timestamptz;

create or replace function public.validate_practice_room_start()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.scenario_id is not null and new.status = 'in_progress' then
    if not exists (
      select 1 from public.scenarios s
      where s.id = new.scenario_id and s.max_turns > 0
    ) then
      raise exception 'invalid scenario max_turns';
    end if;
    if not exists (
      select 1 from public.scenario_success_conditions c
      where c.scenario_id = new.scenario_id and c.is_required
    ) then
      raise exception 'scenario requires at least one required success condition';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists validate_practice_room_start_trigger on public.practice_rooms;
create trigger validate_practice_room_start_trigger
before insert or update of status, scenario_id on public.practice_rooms
for each row execute function public.validate_practice_room_start();

alter table public.interview_documents
  add column if not exists version_no integer not null default 1,
  add column if not exists is_current boolean not null default true,
  add column if not exists upload_status text not null default 'succeeded',
  add column if not exists analysis_status text not null default 'pending',
  add column if not exists replaced_document_id uuid references public.interview_documents(id) on delete set null,
  add column if not exists deleted_at timestamptz,
  add column if not exists updated_at timestamptz not null default now();

alter table public.interview_documents
  drop constraint if exists interview_documents_status_contract,
  add constraint interview_documents_status_contract check (
    upload_status in ('processing', 'succeeded', 'failed', 'deleting', 'deleted')
    and analysis_status in ('pending', 'processing', 'succeeded', 'failed', 'invalidated')
    and version_no > 0
  ) not valid;

create unique index if not exists interview_documents_one_current_type_idx
  on public.interview_documents (setup_id, document_type) where is_current and deleted_at is null;

create table if not exists public.interview_document_analyses (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.interview_documents(id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete cascade,
  idempotency_key uuid not null,
  processing_status text not null default 'processing'
    check (processing_status in ('processing', 'succeeded', 'failed', 'invalidated')),
  extracted_data jsonb not null default '{}'::jsonb,
  citation_evidence jsonb not null default '[]'::jsonb,
  error_code text,
  attempt_count integer not null default 0,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  unique (document_id, idempotency_key)
);

create table if not exists public.room_contexts (
  room_id uuid primary key references public.practice_rooms(id) on delete cascade,
  summary_text text not null default '',
  summarized_through_message_id uuid references public.room_messages(id) on delete set null,
  recent_message_start_sequence integer,
  updated_at timestamptz not null default now()
);

alter table public.session_results
  add column if not exists user_id uuid references auth.users(id) on delete cascade,
  add column if not exists attempt_no integer not null default 1,
  add column if not exists result_status text not null default 'succeeded',
  add column if not exists missing_categories text[] not null default '{}',
  add column if not exists source_snapshot jsonb not null default '{}'::jsonb,
  add column if not exists interview_setup_snapshot jsonb,
  add column if not exists updated_at timestamptz not null default now();

alter table public.session_results
  drop constraint if exists session_results_status_contract,
  add constraint session_results_status_contract
    check (result_status in ('processing', 'partial', 'succeeded', 'failed') and attempt_no > 0) not valid;

-- Result records must survive room deletion. Replace the current room FK, whatever its generated name is.
do $$
declare fk_name text;
begin
  select c.conname into fk_name
  from pg_constraint c
  join pg_attribute a on a.attrelid = c.conrelid and a.attnum = any(c.conkey)
  where c.conrelid = 'public.session_results'::regclass
    and c.contype = 'f' and a.attname = 'room_id'
  limit 1;
  if fk_name is not null then
    execute format('alter table public.session_results drop constraint %I', fk_name);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'session_results_room_id_fkey') then
    alter table public.session_results
      add constraint session_results_room_id_fkey
      foreign key (room_id) references public.practice_rooms(id) on delete set null;
  end if;
end $$;

update public.session_results r
set user_id = p.user_id
from public.practice_rooms p
where r.room_id = p.id and r.user_id is null;

-- Prevent product code from persisting pass/fail hiring decisions.
alter table public.session_results
  drop constraint if exists session_results_no_hiring_decision,
  add constraint session_results_no_hiring_decision check (
    interview_outcome is null or lower(interview_outcome) not in
      ('pass', 'fail', 'passed', 'failed', '합격', '불합격')
  ) not valid;

create table if not exists public.storage_deletion_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  bucket_id text not null,
  storage_path text not null,
  source_type text not null,
  source_id uuid,
  deletion_status text not null default 'pending'
    check (deletion_status in ('pending', 'processing', 'succeeded', 'failed')),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  error_message text,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (bucket_id, storage_path)
);

create index if not exists practice_rooms_user_updated_idx
  on public.practice_rooms (user_id, updated_at desc);
create index if not exists room_messages_room_sequence_idx
  on public.room_messages (room_id, sequence_no);
create index if not exists session_results_user_created_idx
  on public.session_results (user_id, created_at desc);
create index if not exists storage_deletion_jobs_status_created_idx
  on public.storage_deletion_jobs (deletion_status, created_at);
create index if not exists interview_document_analyses_user_started_idx
  on public.interview_document_analyses (user_id, started_at desc);

alter table public.message_ai_processing enable row level security;
alter table public.message_emotion_analysis enable row level security;
alter table public.scenario_success_conditions enable row level security;
alter table public.room_success_condition_progress enable row level security;
alter table public.interview_document_analyses enable row level security;
alter table public.room_contexts enable row level security;
alter table public.storage_deletion_jobs enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='scenario_success_conditions' and policyname='scenario_success_conditions_authenticated_read') then
    create policy scenario_success_conditions_authenticated_read on public.scenario_success_conditions
      for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='message_ai_processing' and policyname='message_ai_processing_own_room') then
    create policy message_ai_processing_own_room on public.message_ai_processing for all to authenticated
      using (exists (select 1 from public.room_messages m join public.practice_rooms r on r.id=m.room_id where m.id=message_id and r.user_id=auth.uid()))
      with check (exists (select 1 from public.room_messages m join public.practice_rooms r on r.id=m.room_id where m.id=message_id and r.user_id=auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='message_emotion_analysis' and policyname='message_emotion_analysis_own_room') then
    create policy message_emotion_analysis_own_room on public.message_emotion_analysis for all to authenticated
      using (exists (select 1 from public.room_messages m join public.practice_rooms r on r.id=m.room_id where m.id=message_id and r.user_id=auth.uid()))
      with check (exists (select 1 from public.room_messages m join public.practice_rooms r on r.id=m.room_id where m.id=message_id and r.user_id=auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='room_success_condition_progress' and policyname='room_success_condition_progress_own_room') then
    create policy room_success_condition_progress_own_room on public.room_success_condition_progress for all to authenticated
      using (exists (select 1 from public.practice_rooms r where r.id=room_id and r.user_id=auth.uid()))
      with check (exists (select 1 from public.practice_rooms r where r.id=room_id and r.user_id=auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='interview_document_analyses' and policyname='interview_document_analyses_own_all') then
    create policy interview_document_analyses_own_all on public.interview_document_analyses for all to authenticated
      using (user_id=auth.uid()) with check (user_id=auth.uid());
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='room_contexts' and policyname='room_contexts_own_room') then
    create policy room_contexts_own_room on public.room_contexts for all to authenticated
      using (exists (select 1 from public.practice_rooms r where r.id=room_id and r.user_id=auth.uid()))
      with check (exists (select 1 from public.practice_rooms r where r.id=room_id and r.user_id=auth.uid()));
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='storage_deletion_jobs' and policyname='storage_deletion_jobs_own_read') then
    create policy storage_deletion_jobs_own_read on public.storage_deletion_jobs for select to authenticated
      using (user_id=auth.uid());
  end if;
end $$;

commit;
