-- Reproduces the processing_jobs/idempotency_records schema already verified in
-- the Supabase project. Safe to apply to the current project or a fresh schema.
-- session_result_generation intentionally has no timeout policy until measured.
begin;

insert into public.processing_timeout_policies (job_type, timeout_seconds, max_attempts, is_active, updated_at)
select v.new_type, p.timeout_seconds, p.max_attempts, p.is_active, now()
from public.processing_timeout_policies p
join (values
  ('ai_response','conversation_text'),
  ('feedback_analysis','turn_feedback'),
  ('interview_analysis','interview_document_analysis'),
  ('interview_configuration','interview_configuration_generation')
) as v(old_type,new_type) on p.job_type=v.old_type
on conflict (job_type) do update set timeout_seconds=excluded.timeout_seconds,
  max_attempts=excluded.max_attempts,is_active=excluded.is_active,updated_at=now();

delete from public.processing_timeout_policies
where job_type in ('ai_response','feedback_analysis','interview_analysis','interview_configuration');

create table if not exists public.processing_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_type text not null,
  status text not null default 'queued',
  progress_stage text,
  completed_units bigint,
  total_units bigint,
  message_ai_processing_id uuid references public.message_ai_processing(id) on delete cascade,
  message_emotion_analysis_id uuid references public.message_emotion_analysis(id) on delete cascade,
  message_audio_id uuid references public.message_audio(id) on delete cascade,
  turn_feedback_id uuid references public.turn_feedback(id) on delete cascade,
  interview_document_analysis_id uuid references public.interview_document_analyses(id) on delete cascade,
  interview_configuration_id uuid references public.interview_configurations(id) on delete cascade,
  session_result_id uuid references public.session_results(id) on delete cascade,
  transport_attempt_count integer not null default 0,
  schema_repair_count smallint not null default 0,
  deadline_at timestamptz,
  next_attempt_at timestamptz,
  error_code text,
  error_retryable boolean,
  error_meta jsonb,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint processing_jobs_job_type_check check (job_type in ('conversation_text','emotion_analysis','tts_generation','turn_feedback','interview_document_analysis','interview_configuration_generation','session_result_generation')),
  constraint processing_jobs_status_check check (status in ('queued','processing','succeeded','failed','cancelled')),
  constraint processing_jobs_target_count_check check (num_nonnulls(message_ai_processing_id,message_emotion_analysis_id,message_audio_id,turn_feedback_id,interview_document_analysis_id,interview_configuration_id,session_result_id)=1),
  constraint processing_jobs_type_target_check check (
    (job_type='conversation_text' and message_ai_processing_id is not null) or
    (job_type='emotion_analysis' and message_emotion_analysis_id is not null) or
    (job_type='tts_generation' and message_audio_id is not null) or
    (job_type='turn_feedback' and turn_feedback_id is not null) or
    (job_type='interview_document_analysis' and interview_document_analysis_id is not null) or
    (job_type='interview_configuration_generation' and interview_configuration_id is not null) or
    (job_type='session_result_generation' and session_result_id is not null)),
  constraint processing_jobs_attempt_check check (transport_attempt_count>=0 and schema_repair_count between 0 and 1),
  constraint processing_jobs_units_check check ((completed_units is null and total_units is null) or (status='processing' and completed_units>=0 and total_units>0 and completed_units<=total_units)),
  constraint processing_jobs_progress_check check (
    (status<>'processing' and progress_stage is null) or
    (status='processing' and (progress_stage is null or
      (job_type='conversation_text' and progress_stage in ('context_preparing','provider_processing','saving_response')) or
      (job_type='emotion_analysis' and progress_stage in ('provider_processing','saving_analysis')) or
      (job_type='tts_generation' and progress_stage in ('provider_processing','storing_audio')) or
      (job_type='turn_feedback' and progress_stage in ('provider_processing','saving_feedback')) or
      (job_type='interview_document_analysis' and progress_stage in ('extracting_text','chunking','embedding','saving_analysis')) or
      (job_type='interview_configuration_generation' and progress_stage in ('retrieving_evidence','provider_processing','saving_configuration')) or
      (job_type='session_result_generation' and progress_stage in ('aggregating_evidence','provider_processing','saving_result'))))),
  constraint processing_jobs_terminal_shape_check check (
    ((status in ('succeeded','failed','cancelled'))=(completed_at is not null)) and
    (status<>'processing' or started_at is not null) and
    ((status='failed' and error_code is not null and error_retryable is not null) or
     (status<>'failed' and error_code is null and error_retryable is null and error_meta is null)) and
    (error_meta is null or jsonb_typeof(error_meta)='object'))
);

create unique index if not exists processing_jobs_active_ai_idx on public.processing_jobs(message_ai_processing_id) where status in ('queued','processing') and message_ai_processing_id is not null;
create unique index if not exists processing_jobs_active_emotion_idx on public.processing_jobs(message_emotion_analysis_id) where status in ('queued','processing') and message_emotion_analysis_id is not null;
create unique index if not exists processing_jobs_active_audio_idx on public.processing_jobs(message_audio_id) where status in ('queued','processing') and message_audio_id is not null;
create unique index if not exists processing_jobs_active_feedback_idx on public.processing_jobs(turn_feedback_id) where status in ('queued','processing') and turn_feedback_id is not null;
create unique index if not exists processing_jobs_active_document_idx on public.processing_jobs(interview_document_analysis_id) where status in ('queued','processing') and interview_document_analysis_id is not null;
create unique index if not exists processing_jobs_active_configuration_idx on public.processing_jobs(interview_configuration_id) where status in ('queued','processing') and interview_configuration_id is not null;
create unique index if not exists processing_jobs_active_result_idx on public.processing_jobs(session_result_id) where status in ('queued','processing') and session_result_id is not null;
create index if not exists processing_jobs_owner_created_idx on public.processing_jobs(user_id,created_at desc,id desc);
create index if not exists processing_jobs_claim_idx on public.processing_jobs(status,next_attempt_at,created_at) where status='queued';
create index if not exists processing_jobs_deadline_idx on public.processing_jobs(deadline_at) where status in ('queued','processing');

create table if not exists public.idempotency_records (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  action_scope text not null,
  idempotency_key uuid not null,
  request_fingerprint bytea not null,
  state text not null default 'in_progress',
  claim_token uuid,
  lease_expires_at timestamptz,
  response_status smallint,
  response_body jsonb,
  response_schema_version text,
  processing_job_id uuid references public.processing_jobs(id) on delete set null,
  resource_type text,
  resource_id uuid,
  error_code text,
  error_retryable boolean,
  error_meta jsonb,
  completed_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint idempotency_records_action_scope_check check (action_scope in ('room.create','room.delete','room_message.create','message_response.retry','message_feedback.retry','message_tts.retry','message_repeat.create','room_result.retry','result.delete','interview_document.create','interview_document.analyze','interview_document.replace','interview_document.delete','interview_configuration.generate','interview_configuration.regenerate','interview_practice_room.create','onboarding.complete','account.delete')),
  constraint idempotency_records_fingerprint_check check (octet_length(request_fingerprint)=32),
  constraint idempotency_records_state_check check (state in ('in_progress','completed','failed')),
  constraint idempotency_records_resource_pair_check check ((resource_type is null)=(resource_id is null)),
  constraint idempotency_records_json_check check ((response_body is null or jsonb_typeof(response_body)='object') and (error_meta is null or jsonb_typeof(error_meta)='object')),
  constraint idempotency_records_state_shape_check check (
    (state='in_progress' and claim_token is not null and lease_expires_at is not null and completed_at is null and expires_at is null and response_status is null and response_body is null and response_schema_version is null and error_code is null and error_retryable is null and error_meta is null) or
    (state='completed' and claim_token is null and lease_expires_at is null and response_status between 200 and 299 and response_schema_version is not null and completed_at is not null and expires_at>completed_at and error_code is null and error_retryable is null and error_meta is null and ((response_status=204 and response_body is null) or (response_status<>204 and jsonb_typeof(response_body)='object'))) or
    (state='failed' and claim_token is null and lease_expires_at is null and completed_at is not null and expires_at>completed_at and error_code is not null and error_retryable is not null and ((error_retryable and response_status is null and response_body is null and response_schema_version is null) or (not error_retryable and response_status between 400 and 499 and response_status<>429 and jsonb_typeof(response_body)='object' and response_schema_version is not null)))) ,
  unique(user_id,action_scope,idempotency_key)
);

create index if not exists idempotency_records_job_idx on public.idempotency_records(processing_job_id) where processing_job_id is not null;
create index if not exists idempotency_records_lease_idx on public.idempotency_records(lease_expires_at) where state='in_progress';
create index if not exists idempotency_records_expiry_idx on public.idempotency_records(expires_at) where state in ('completed','failed');

create or replace function public.set_architecture_record_updated_at() returns trigger language plpgsql set search_path=public,pg_temp as $$ begin new.updated_at=now(); return new; end $$;

create or replace function public.validate_processing_job_owner_target() returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
declare v_owner uuid;
begin
  case new.job_type
    when 'conversation_text' then select r.user_id into v_owner from public.message_ai_processing p join public.room_messages m on m.id=p.message_id join public.practice_rooms r on r.id=m.room_id where p.id=new.message_ai_processing_id;
    when 'emotion_analysis' then select r.user_id into v_owner from public.message_emotion_analysis e join public.room_messages m on m.id=e.message_id join public.practice_rooms r on r.id=m.room_id where e.id=new.message_emotion_analysis_id;
    when 'tts_generation' then select r.user_id into v_owner from public.message_audio a join public.room_messages m on m.id=a.message_id join public.practice_rooms r on r.id=m.room_id where a.id=new.message_audio_id;
    when 'turn_feedback' then select r.user_id into v_owner from public.turn_feedback f join public.room_messages m on m.id=f.message_id join public.practice_rooms r on r.id=m.room_id where f.id=new.turn_feedback_id;
    when 'interview_document_analysis' then select a.user_id into v_owner from public.interview_document_analyses a where a.id=new.interview_document_analysis_id;
    when 'interview_configuration_generation' then select c.user_id into v_owner from public.interview_configurations c where c.id=new.interview_configuration_id;
    when 'session_result_generation' then select s.user_id into v_owner from public.session_results s where s.id=new.session_result_id;
  end case;
  if v_owner is null or v_owner<>new.user_id then raise exception using errcode='23514',message='processing job owner does not match target owner'; end if;
  return new;
end $$;

create or replace function public.validate_processing_job_transition() returns trigger language plpgsql set search_path=public,pg_temp as $$
begin
  if old.status in ('succeeded','failed','cancelled') then raise exception using errcode='23514',message='terminal processing job is immutable'; end if;
  if new.status=old.status then return new; end if;
  if old.status='queued' and new.status not in ('processing','failed','cancelled') then raise exception using errcode='23514',message='invalid queued job transition'; end if;
  if old.status='processing' and new.status not in ('queued','succeeded','failed','cancelled') then raise exception using errcode='23514',message='invalid processing job transition'; end if;
  return new;
end $$;

create or replace function public.validate_processing_job_domain_state() returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
declare v_domain_status text; v_valid boolean:=false;
begin
  if new.status='cancelled' then return null; end if;
  case new.job_type
    when 'conversation_text' then select processing_status into v_domain_status from public.message_ai_processing where id=new.message_ai_processing_id;
    when 'emotion_analysis' then select processing_status into v_domain_status from public.message_emotion_analysis where id=new.message_emotion_analysis_id;
    when 'tts_generation' then select generation_status into v_domain_status from public.message_audio where id=new.message_audio_id;
    when 'turn_feedback' then select analysis_status into v_domain_status from public.turn_feedback where id=new.turn_feedback_id;
    when 'interview_document_analysis' then select processing_status into v_domain_status from public.interview_document_analyses where id=new.interview_document_analysis_id;
    when 'interview_configuration_generation' then select status into v_domain_status from public.interview_configurations where id=new.interview_configuration_id;
    when 'session_result_generation' then select result_status into v_domain_status from public.session_results where id=new.session_result_id;
  end case;
  if new.status in ('queued','processing') then v_valid:=v_domain_status='processing';
  elsif new.status='failed' then v_valid:=v_domain_status='failed';
  elsif new.status='succeeded' and new.job_type in ('conversation_text','emotion_analysis','interview_document_analysis') then v_valid:=v_domain_status='succeeded';
  elsif new.status='succeeded' and new.job_type='tts_generation' then v_valid:=v_domain_status='ready';
  elsif new.status='succeeded' and new.job_type='turn_feedback' then v_valid:=v_domain_status in ('ready','partial');
  elsif new.status='succeeded' and new.job_type='interview_configuration_generation' then v_valid:=v_domain_status='ready';
  elsif new.status='succeeded' and new.job_type='session_result_generation' then v_valid:=v_domain_status in ('partial','succeeded'); end if;
  if not coalesce(v_valid,false) then raise exception using errcode='23514',message='processing job/domain status mismatch'; end if;
  return null;
end $$;

create or replace function public.validate_idempotency_job_owner() returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
begin if new.processing_job_id is not null and not exists(select 1 from public.processing_jobs j where j.id=new.processing_job_id and j.user_id=new.user_id) then raise exception using errcode='23514',message='idempotency job owner mismatch'; end if; return new; end $$;

create or replace function public.validate_idempotency_transition() returns trigger language plpgsql set search_path=public,pg_temp as $$
declare v_only_job_unlink boolean;
begin
  v_only_job_unlink:=old.processing_job_id is not null and new.processing_job_id is null and new.state=old.state and (to_jsonb(new)-'processing_job_id'-'updated_at')=(to_jsonb(old)-'processing_job_id'-'updated_at');
  if old.state='completed' then if v_only_job_unlink then return new; end if; raise exception using errcode='23514',message='completed idempotency record is immutable'; end if;
  if old.state='failed' and not old.error_retryable then if v_only_job_unlink then return new; end if; raise exception using errcode='23514',message='terminal idempotency failure is immutable'; end if;
  if new.state=old.state then return new; end if;
  if old.state='in_progress' and new.state not in ('completed','failed') then raise exception using errcode='23514',message='invalid idempotency transition'; end if;
  if old.state='failed' and old.error_retryable and new.state<>'in_progress' then raise exception using errcode='23514',message='retryable failure requires CAS recovery claim'; end if;
  return new;
end $$;

create or replace function public.purge_expired_idempotency_records(p_batch_size integer) returns integer language plpgsql security definer set search_path=public,pg_temp as $$
declare v_count integer;
begin
  if p_batch_size is null or p_batch_size<=0 then raise exception using errcode='22023',message='positive batch size required'; end if;
  with candidates as (select id from public.idempotency_records where state in ('completed','failed') and expires_at<=now() order by expires_at,id for update skip locked limit p_batch_size), deleted as (delete from public.idempotency_records r using candidates c where r.id=c.id returning 1) select count(*) into v_count from deleted;
  return v_count;
end $$;

drop trigger if exists processing_jobs_owner_target_trigger on public.processing_jobs;
create trigger processing_jobs_owner_target_trigger before insert or update of user_id,job_type,message_ai_processing_id,message_emotion_analysis_id,message_audio_id,turn_feedback_id,interview_document_analysis_id,interview_configuration_id,session_result_id on public.processing_jobs for each row execute function public.validate_processing_job_owner_target();
drop trigger if exists processing_jobs_transition_trigger on public.processing_jobs;
create trigger processing_jobs_transition_trigger before update on public.processing_jobs for each row execute function public.validate_processing_job_transition();
drop trigger if exists processing_jobs_updated_at_trigger on public.processing_jobs;
create trigger processing_jobs_updated_at_trigger before update on public.processing_jobs for each row execute function public.set_architecture_record_updated_at();
drop trigger if exists processing_jobs_domain_state_trigger on public.processing_jobs;
create constraint trigger processing_jobs_domain_state_trigger after insert or update on public.processing_jobs deferrable initially deferred for each row execute function public.validate_processing_job_domain_state();
drop trigger if exists idempotency_records_job_owner_trigger on public.idempotency_records;
create trigger idempotency_records_job_owner_trigger before insert or update of user_id,processing_job_id on public.idempotency_records for each row execute function public.validate_idempotency_job_owner();
drop trigger if exists idempotency_records_transition_trigger on public.idempotency_records;
create trigger idempotency_records_transition_trigger before update on public.idempotency_records for each row execute function public.validate_idempotency_transition();
drop trigger if exists idempotency_records_updated_at_trigger on public.idempotency_records;
create trigger idempotency_records_updated_at_trigger before update on public.idempotency_records for each row execute function public.set_architecture_record_updated_at();

alter table public.processing_jobs enable row level security;
alter table public.idempotency_records enable row level security;
revoke insert,update,delete on public.processing_jobs from anon,authenticated;
grant select on public.processing_jobs to authenticated;
drop policy if exists processing_jobs_own_read on public.processing_jobs;
create policy processing_jobs_own_read on public.processing_jobs for select to authenticated using (user_id=auth.uid());
revoke all on public.idempotency_records from anon,authenticated;
revoke all on function public.validate_processing_job_owner_target() from public;
revoke all on function public.validate_processing_job_transition() from public;
revoke all on function public.validate_processing_job_domain_state() from public;
revoke all on function public.validate_idempotency_job_owner() from public;
revoke all on function public.validate_idempotency_transition() from public;
revoke all on function public.purge_expired_idempotency_records(integer) from public;

commit;
