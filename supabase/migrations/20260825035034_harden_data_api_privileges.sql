-- Keep Data API exposure opt-in for objects created by this repository's
-- postgres-owned migration chain. Dashboard schema changes are not a source of
-- truth for this project.
alter default privileges for role postgres in schema public
  revoke all privileges on tables from public, anon, authenticated, service_role;

alter default privileges for role postgres in schema public
  revoke all privileges on sequences from public, anon, authenticated, service_role;

alter default privileges for role postgres in schema public
  revoke all privileges on functions from public, anon, authenticated, service_role;

-- Start from a closed Data API surface for the low-privilege roles.
revoke all privileges on all tables in schema public from public, anon, authenticated;
revoke all privileges on all sequences in schema public from public, anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;

-- Catalog and user-visible job state are read-only through the Data API.
grant select on table
  public.consent_policies,
  public.persona_scenarios,
  public.personas,
  public.processing_jobs,
  public.scenario_success_conditions,
  public.scenarios,
  public.storage_deletion_jobs
to authenticated;

-- User-owned rows remain subject to their existing authenticated RLS policies.
grant select, insert, update, delete on table
  public.feedback_emotions,
  public.feedback_scores,
  public.interview_answers,
  public.interview_configurations,
  public.interview_document_analyses,
  public.interview_documents,
  public.interview_questions,
  public.interview_setups,
  public.message_ai_processing,
  public.message_audio,
  public.message_emotion_analysis,
  public.practice_rooms,
  public.profiles,
  public.result_items,
  public.room_contexts,
  public.room_messages,
  public.room_success_condition_progress,
  public.session_results,
  public.turn_feedback,
  public.user_consents
to authenticated;

-- idempotency_records and processing_timeout_policies intentionally receive no
-- anon/authenticated grant. Internal and trigger functions are not RPC APIs.
