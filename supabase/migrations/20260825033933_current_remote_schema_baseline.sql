-- Baseline captured from Supabase project txufuwppuyhmphyehbdb on 2026-08-25.
-- It preserves the actual public schema before contract corrections.
-- Historical incremental migrations are retained under supabase/migration_history/.

set check_function_bodies = off;
set search_path = public, extensions;

-- Tables

create table public.consent_policies (
  id uuid default gen_random_uuid() not null,
  consent_type text not null,
  policy_version text not null,
  is_required boolean default true not null,
  is_active boolean default true not null,
  effective_at timestamp with time zone default now() not null,
  created_at timestamp with time zone default now() not null
);

create table public.feedback_emotions (
  id uuid default gen_random_uuid() not null,
  feedback_id uuid not null,
  emotion_label text not null,
  percentage numeric(5,2),
  impression_text text,
  sort_order integer default 0 not null,
  analysis_source text default 'text'::text not null,
  evidence_text text
);

create table public.feedback_scores (
  id uuid default gen_random_uuid() not null,
  feedback_id uuid not null,
  category text not null,
  score numeric(5,2),
  max_score numeric(5,2) default 25 not null,
  strength_text text,
  suggestion_text text,
  original_expression text,
  recommended_expression text
);

create table public.idempotency_records (
  id uuid default gen_random_uuid() not null,
  user_id uuid not null,
  action_scope text not null,
  idempotency_key uuid not null,
  request_fingerprint bytea not null,
  state text default 'in_progress'::text not null,
  claim_token uuid,
  lease_expires_at timestamp with time zone,
  response_status smallint,
  response_body jsonb,
  response_schema_version text,
  processing_job_id uuid,
  resource_type text,
  resource_id uuid,
  error_code text,
  error_retryable boolean,
  error_meta jsonb,
  completed_at timestamp with time zone,
  expires_at timestamp with time zone,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null
);

create table public.interview_answers (
  id uuid default gen_random_uuid() not null,
  question_id uuid not null,
  room_id uuid not null,
  message_id uuid not null,
  answer_attempt_no integer default 1 not null,
  is_current boolean default true not null,
  submitted_at timestamp with time zone default now() not null,
  created_at timestamp with time zone default now() not null
);

create table public.interview_configurations (
  id uuid default gen_random_uuid() not null,
  setup_id uuid not null,
  user_id uuid not null,
  version_no integer not null,
  status text default 'processing'::text not null,
  idempotency_key uuid not null,
  document_version_snapshot jsonb default '{}'::jsonb not null,
  analysis_ids uuid[] default '{}'::uuid[] not null,
  question_count smallint default 0 not null,
  processing_token uuid default gen_random_uuid() not null,
  deadline_at timestamp with time zone,
  next_attempt_at timestamp with time zone,
  attempt_count integer default 0 not null,
  error_code text,
  error_message text,
  created_at timestamp with time zone default now() not null,
  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  invalidated_at timestamp with time zone,
  updated_at timestamp with time zone default now() not null
);

create table public.interview_document_analyses (
  id uuid default gen_random_uuid() not null,
  document_id uuid not null,
  user_id uuid not null,
  idempotency_key uuid not null,
  processing_status text default 'processing'::text not null,
  extracted_data jsonb default '{}'::jsonb not null,
  citation_evidence jsonb default '[]'::jsonb not null,
  error_code text,
  attempt_count integer default 0 not null,
  started_at timestamp with time zone default now() not null,
  completed_at timestamp with time zone,
  updated_at timestamp with time zone default now() not null,
  processing_token uuid default gen_random_uuid() not null,
  deadline_at timestamp with time zone,
  next_attempt_at timestamp with time zone
);

create table public.interview_documents (
  id uuid default gen_random_uuid() not null,
  setup_id uuid not null,
  user_id uuid not null,
  document_type text not null,
  original_filename text not null,
  storage_path text not null,
  mime_type text,
  size_bytes bigint,
  processing_status text default 'uploaded'::text not null,
  extracted_content jsonb,
  uploaded_at timestamp with time zone default now() not null,
  processed_at timestamp with time zone,
  version_no integer default 1 not null,
  is_current boolean default true not null,
  upload_status text default 'succeeded'::text not null,
  analysis_status text default 'pending'::text not null,
  replaced_document_id uuid,
  deleted_at timestamp with time zone,
  updated_at timestamp with time zone default now() not null
);

create table public.interview_questions (
  id uuid default gen_random_uuid() not null,
  configuration_id uuid not null,
  sequence_no smallint not null,
  question_text text not null,
  question_type text default 'required'::text not null,
  is_required boolean default true not null,
  source_evidence jsonb default '[]'::jsonb not null,
  evaluation_focus jsonb default '[]'::jsonb not null,
  created_at timestamp with time zone default now() not null
);

create table public.interview_setups (
  id uuid default gen_random_uuid() not null,
  user_id uuid not null,
  desired_role text not null,
  application_type text,
  status text default 'draft'::text not null,
  preparation_progress smallint default 0 not null,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null
);

create table public.message_ai_processing (
  id uuid default gen_random_uuid() not null,
  message_id uuid not null,
  processing_status text default 'processing'::text not null,
  error_code text,
  error_message text,
  attempt_count integer default 0 not null,
  started_at timestamp with time zone default now() not null,
  completed_at timestamp with time zone,
  updated_at timestamp with time zone default now() not null,
  processing_token uuid default gen_random_uuid() not null,
  deadline_at timestamp with time zone,
  next_attempt_at timestamp with time zone
);

create table public.message_audio (
  id uuid default gen_random_uuid() not null,
  message_id uuid not null,
  audio_type text not null,
  storage_path text not null,
  duration_ms integer,
  generation_status text default 'ready'::text not null,
  created_at timestamp with time zone default now() not null,
  is_current boolean default true not null,
  replacement_for_id uuid,
  error_code text,
  attempt_count integer default 0 not null,
  completed_at timestamp with time zone,
  updated_at timestamp with time zone default now() not null,
  processing_token uuid default gen_random_uuid() not null,
  deadline_at timestamp with time zone,
  next_attempt_at timestamp with time zone
);

create table public.message_emotion_analysis (
  id uuid default gen_random_uuid() not null,
  message_id uuid not null,
  processing_status text default 'processing'::text not null,
  emotion_label text,
  reasoning text,
  error_code text,
  attempt_count integer default 0 not null,
  started_at timestamp with time zone default now() not null,
  completed_at timestamp with time zone,
  updated_at timestamp with time zone default now() not null,
  processing_token uuid default gen_random_uuid() not null,
  deadline_at timestamp with time zone,
  next_attempt_at timestamp with time zone
);

create table public.persona_scenarios (
  persona_id uuid not null,
  scenario_id uuid not null,
  relationship_label text
);

create table public.personas (
  id uuid default gen_random_uuid() not null,
  name text not null,
  role_title text,
  description text,
  avatar_key text,
  is_active boolean default true not null,
  sort_order integer default 0 not null,
  created_at timestamp with time zone default now() not null
);

create table public.practice_rooms (
  id uuid default gen_random_uuid() not null,
  user_id uuid not null,
  practice_type text not null,
  persona_id uuid,
  scenario_id uuid,
  interview_setup_id uuid,
  title text not null,
  goal_snapshot text,
  status text default 'in_progress'::text not null,
  turn_count integer default 0 not null,
  started_at timestamp with time zone default now() not null,
  completed_at timestamp with time zone,
  updated_at timestamp with time zone default now() not null,
  ended_reason text,
  last_confirmed_turn_at timestamp with time zone,
  interview_configuration_id uuid
);

create table public.processing_jobs (
  id uuid default gen_random_uuid() not null,
  user_id uuid not null,
  job_type text not null,
  status text default 'queued'::text not null,
  progress_stage text,
  completed_units bigint,
  total_units bigint,
  message_ai_processing_id uuid,
  message_emotion_analysis_id uuid,
  message_audio_id uuid,
  turn_feedback_id uuid,
  interview_document_analysis_id uuid,
  interview_configuration_id uuid,
  session_result_id uuid,
  transport_attempt_count integer default 0 not null,
  schema_repair_count smallint default 0 not null,
  deadline_at timestamp with time zone,
  next_attempt_at timestamp with time zone,
  error_code text,
  error_retryable boolean,
  error_meta jsonb,
  started_at timestamp with time zone,
  completed_at timestamp with time zone,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null
);

create table public.processing_timeout_policies (
  job_type text not null,
  timeout_seconds integer not null,
  max_attempts integer default 3 not null,
  is_active boolean default true not null,
  updated_at timestamp with time zone default now() not null
);

create table public.profiles (
  id uuid not null,
  display_name text,
  birth_date date,
  gender text,
  native_language text,
  display_language text default 'ko'::text not null,
  onboarding_completed boolean default false not null,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null
);

create table public.result_items (
  id uuid default gen_random_uuid() not null,
  result_id uuid not null,
  item_type text not null,
  category text,
  title text not null,
  original_expression text,
  recommended_expression text,
  explanation text,
  evidence_text text,
  source_document_id uuid,
  sort_order integer default 0 not null,
  created_at timestamp with time zone default now() not null
);

create table public.room_contexts (
  room_id uuid not null,
  summary_text text default ''::text not null,
  summarized_through_message_id uuid,
  recent_message_start_sequence integer,
  updated_at timestamp with time zone default now() not null
);

create table public.room_messages (
  id uuid default gen_random_uuid() not null,
  room_id uuid not null,
  sequence_no integer not null,
  sender_type text not null,
  content text not null,
  input_mode text,
  delivery_status text default 'sent'::text not null,
  transcript_confirmed boolean default false not null,
  persona_emotion text,
  created_at timestamp with time zone default now() not null,
  client_request_id uuid,
  reply_to_message_id uuid,
  processing_error text,
  updated_at timestamp with time zone default now() not null
);

create table public.room_success_condition_progress (
  id uuid default gen_random_uuid() not null,
  room_id uuid not null,
  condition_id uuid not null,
  achieved boolean default false not null,
  evidence_message_id uuid,
  reasoning text,
  evaluated_at timestamp with time zone
);

create table public.scenario_success_conditions (
  id uuid default gen_random_uuid() not null,
  scenario_id uuid not null,
  condition_key text not null,
  description text not null,
  is_required boolean default true not null,
  sort_order integer default 0 not null,
  created_at timestamp with time zone default now() not null
);

create table public.scenarios (
  id uuid default gen_random_uuid() not null,
  practice_type text not null,
  title text not null,
  goal text,
  location text,
  difficulty text,
  estimated_minutes integer,
  opening_message text,
  max_turns integer,
  is_active boolean default true not null,
  sort_order integer default 0 not null,
  created_at timestamp with time zone default now() not null
);

create table public.session_results (
  id uuid default gen_random_uuid() not null,
  room_id uuid,
  overall_score numeric(5,2),
  summary text,
  goal_achieved boolean,
  interview_outcome text,
  duration_seconds integer,
  created_at timestamp with time zone default now() not null,
  user_id uuid not null,
  attempt_no integer default 1 not null,
  result_status text default 'succeeded'::text not null,
  missing_categories text[] default '{}'::text[] not null,
  source_snapshot jsonb default '{}'::jsonb not null,
  interview_setup_snapshot jsonb,
  updated_at timestamp with time zone default now() not null
);

create table public.storage_deletion_jobs (
  id uuid default gen_random_uuid() not null,
  user_id uuid not null,
  bucket_id text not null,
  storage_path text not null,
  source_type text not null,
  source_id uuid,
  deletion_status text default 'pending'::text not null,
  attempt_count integer default 0 not null,
  error_message text,
  created_at timestamp with time zone default now() not null,
  completed_at timestamp with time zone,
  max_attempts integer default 5 not null,
  next_attempt_at timestamp with time zone default now() not null,
  locked_at timestamp with time zone,
  locked_by text,
  lock_expires_at timestamp with time zone,
  error_code text,
  updated_at timestamp with time zone default now() not null
);

create table public.turn_feedback (
  id uuid default gen_random_uuid() not null,
  message_id uuid not null,
  overall_score numeric(5,2),
  summary text,
  source_duration_ms integer,
  analysis_status text default 'ready'::text not null,
  created_at timestamp with time zone default now() not null,
  updated_at timestamp with time zone default now() not null,
  error_code text,
  attempt_count integer default 0 not null,
  processing_token uuid default gen_random_uuid() not null,
  deadline_at timestamp with time zone,
  next_attempt_at timestamp with time zone
);

create table public.user_consents (
  id uuid default gen_random_uuid() not null,
  user_id uuid not null,
  consent_type text not null,
  policy_version text not null,
  accepted_at timestamp with time zone default now() not null,
  revoked_at timestamp with time zone
);

-- Primary and unique constraints

alter table public.consent_policies add constraint consent_policies_consent_type_policy_version_key UNIQUE (consent_type, policy_version);

alter table public.consent_policies add constraint consent_policies_pkey PRIMARY KEY (id);

alter table public.feedback_emotions add constraint feedback_emotions_feedback_label_key UNIQUE (feedback_id, emotion_label);

alter table public.feedback_emotions add constraint feedback_emotions_pkey PRIMARY KEY (id);

alter table public.feedback_scores add constraint feedback_scores_feedback_category_key UNIQUE (feedback_id, category);

alter table public.feedback_scores add constraint feedback_scores_feedback_id_category_key UNIQUE (feedback_id, category);

alter table public.feedback_scores add constraint feedback_scores_pkey PRIMARY KEY (id);

alter table public.idempotency_records add constraint idempotency_records_pkey PRIMARY KEY (id);

alter table public.idempotency_records add constraint idempotency_records_user_id_action_scope_idempotency_key_key UNIQUE (user_id, action_scope, idempotency_key);

alter table public.interview_answers add constraint interview_answers_message_id_key UNIQUE (message_id);

alter table public.interview_answers add constraint interview_answers_pkey PRIMARY KEY (id);

alter table public.interview_answers add constraint interview_answers_question_id_answer_attempt_no_key UNIQUE (question_id, answer_attempt_no);

alter table public.interview_configurations add constraint interview_configurations_pkey PRIMARY KEY (id);

alter table public.interview_configurations add constraint interview_configurations_setup_id_idempotency_key_key UNIQUE (setup_id, idempotency_key);

alter table public.interview_configurations add constraint interview_configurations_setup_id_version_no_key UNIQUE (setup_id, version_no);

alter table public.interview_document_analyses add constraint interview_document_analyses_document_id_idempotency_key_key UNIQUE (document_id, idempotency_key);

alter table public.interview_document_analyses add constraint interview_document_analyses_pkey PRIMARY KEY (id);

alter table public.interview_documents add constraint interview_documents_pkey PRIMARY KEY (id);

alter table public.interview_questions add constraint interview_questions_configuration_id_sequence_no_key UNIQUE (configuration_id, sequence_no);

alter table public.interview_questions add constraint interview_questions_pkey PRIMARY KEY (id);

alter table public.interview_setups add constraint interview_setups_pkey PRIMARY KEY (id);

alter table public.message_ai_processing add constraint message_ai_processing_message_id_key UNIQUE (message_id);

alter table public.message_ai_processing add constraint message_ai_processing_pkey PRIMARY KEY (id);

alter table public.message_audio add constraint message_audio_pkey PRIMARY KEY (id);

alter table public.message_emotion_analysis add constraint message_emotion_analysis_message_id_key UNIQUE (message_id);

alter table public.message_emotion_analysis add constraint message_emotion_analysis_pkey PRIMARY KEY (id);

alter table public.persona_scenarios add constraint persona_scenarios_pkey PRIMARY KEY (persona_id, scenario_id);

alter table public.personas add constraint personas_pkey PRIMARY KEY (id);

alter table public.practice_rooms add constraint practice_rooms_pkey PRIMARY KEY (id);

alter table public.processing_jobs add constraint processing_jobs_pkey PRIMARY KEY (id);

alter table public.processing_timeout_policies add constraint processing_timeout_policies_pkey PRIMARY KEY (job_type);

alter table public.profiles add constraint profiles_pkey PRIMARY KEY (id);

alter table public.result_items add constraint result_items_pkey PRIMARY KEY (id);

alter table public.room_contexts add constraint room_contexts_pkey PRIMARY KEY (room_id);

alter table public.room_messages add constraint room_messages_pkey PRIMARY KEY (id);

alter table public.room_messages add constraint room_messages_reply_to_key UNIQUE (reply_to_message_id);

alter table public.room_messages add constraint room_messages_room_client_request_key UNIQUE (room_id, client_request_id);

alter table public.room_messages add constraint room_messages_room_id_sequence_no_key UNIQUE (room_id, sequence_no);

alter table public.room_messages add constraint room_messages_room_sequence_key UNIQUE (room_id, sequence_no);

alter table public.room_success_condition_progress add constraint room_success_condition_progress_pkey PRIMARY KEY (id);

alter table public.room_success_condition_progress add constraint room_success_condition_progress_room_id_condition_id_key UNIQUE (room_id, condition_id);

alter table public.scenario_success_conditions add constraint scenario_success_conditions_pkey PRIMARY KEY (id);

alter table public.scenario_success_conditions add constraint scenario_success_conditions_scenario_id_condition_key_key UNIQUE (scenario_id, condition_key);

alter table public.scenarios add constraint scenarios_pkey PRIMARY KEY (id);

alter table public.session_results add constraint session_results_pkey PRIMARY KEY (id);

alter table public.session_results add constraint session_results_room_id_key UNIQUE (room_id);

alter table public.storage_deletion_jobs add constraint storage_deletion_jobs_bucket_id_storage_path_key UNIQUE (bucket_id, storage_path);

alter table public.storage_deletion_jobs add constraint storage_deletion_jobs_pkey PRIMARY KEY (id);

alter table public.turn_feedback add constraint turn_feedback_message_id_key UNIQUE (message_id);

alter table public.turn_feedback add constraint turn_feedback_message_key UNIQUE (message_id);

alter table public.turn_feedback add constraint turn_feedback_pkey PRIMARY KEY (id);

alter table public.user_consents add constraint user_consents_pkey PRIMARY KEY (id);

alter table public.user_consents add constraint user_consents_user_id_consent_type_policy_version_key UNIQUE (user_id, consent_type, policy_version);

-- Check constraints

alter table public.feedback_emotions add constraint feedback_emotions_analysis_source_contract CHECK (analysis_source = ANY (ARRAY['text'::text, 'voice'::text])) NOT VALID;

alter table public.feedback_emotions add constraint feedback_emotions_percentage_check CHECK (percentage IS NULL OR percentage >= 0::numeric AND percentage <= 100::numeric);

alter table public.feedback_emotions add constraint feedback_emotions_percentage_contract CHECK (percentage >= 0::numeric AND percentage <= 100::numeric AND sort_order >= 1 AND sort_order <= 3) NOT VALID;

alter table public.feedback_scores add constraint feedback_scores_category_check CHECK (category = ANY (ARRAY['honorifics'::text, 'consideration'::text, 'context_fit'::text, 'naturalness'::text]));

alter table public.feedback_scores add constraint feedback_scores_max_check CHECK (max_score > 0::numeric);

alter table public.feedback_scores add constraint feedback_scores_score_contract CHECK ((category = ANY (ARRAY['honorifics'::text, 'consideration'::text, 'context_fit'::text, 'naturalness'::text])) AND score >= 0::numeric AND score <= 25::numeric AND score = trunc(score) AND max_score = 25::numeric);

alter table public.feedback_scores add constraint feedback_scores_value_check CHECK (score IS NULL OR score >= 0::numeric AND score <= max_score);

alter table public.idempotency_records add constraint idempotency_records_action_scope_check CHECK (action_scope = ANY (ARRAY['room.create'::text, 'room.delete'::text, 'room_message.create'::text, 'message_response.retry'::text, 'message_feedback.retry'::text, 'message_tts.retry'::text, 'message_repeat.create'::text, 'room_result.retry'::text, 'result.delete'::text, 'interview_document.create'::text, 'interview_document.analyze'::text, 'interview_document.replace'::text, 'interview_document.delete'::text, 'interview_configuration.generate'::text, 'interview_configuration.regenerate'::text, 'interview_practice_room.create'::text, 'onboarding.complete'::text, 'account.delete'::text]));

alter table public.idempotency_records add constraint idempotency_records_fingerprint_check CHECK (octet_length(request_fingerprint) = 32);

alter table public.idempotency_records add constraint idempotency_records_json_check CHECK ((response_body IS NULL OR jsonb_typeof(response_body) = 'object'::text) AND (error_meta IS NULL OR jsonb_typeof(error_meta) = 'object'::text));

alter table public.idempotency_records add constraint idempotency_records_resource_pair_check CHECK ((resource_type IS NULL) = (resource_id IS NULL));

alter table public.idempotency_records add constraint idempotency_records_state_check CHECK (state = ANY (ARRAY['in_progress'::text, 'completed'::text, 'failed'::text]));

alter table public.idempotency_records add constraint idempotency_records_state_shape_check CHECK (state = 'in_progress'::text AND claim_token IS NOT NULL AND lease_expires_at IS NOT NULL AND completed_at IS NULL AND expires_at IS NULL AND response_status IS NULL AND response_body IS NULL AND response_schema_version IS NULL AND error_code IS NULL AND error_retryable IS NULL AND error_meta IS NULL OR state = 'completed'::text AND claim_token IS NULL AND lease_expires_at IS NULL AND response_status >= 200 AND response_status <= 299 AND response_schema_version IS NOT NULL AND completed_at IS NOT NULL AND expires_at > completed_at AND error_code IS NULL AND error_retryable IS NULL AND error_meta IS NULL AND (response_status = 204 AND response_body IS NULL OR response_status <> 204 AND jsonb_typeof(response_body) = 'object'::text) OR state = 'failed'::text AND claim_token IS NULL AND lease_expires_at IS NULL AND completed_at IS NOT NULL AND expires_at > completed_at AND error_code IS NOT NULL AND error_retryable IS NOT NULL AND (error_retryable AND response_status IS NULL AND response_body IS NULL AND response_schema_version IS NULL OR NOT error_retryable AND response_status >= 400 AND response_status <= 499 AND response_status <> 429 AND jsonb_typeof(response_body) = 'object'::text AND response_schema_version IS NOT NULL));

alter table public.interview_answers add constraint interview_answers_answer_attempt_no_check CHECK (answer_attempt_no > 0);

alter table public.interview_configurations add constraint interview_configurations_attempt_count_check CHECK (attempt_count >= 0);

alter table public.interview_configurations add constraint interview_configurations_check CHECK ((status <> ALL (ARRAY['ready'::text, 'in_progress'::text, 'completed'::text])) OR question_count >= 1 AND question_count <= 10);

alter table public.interview_configurations add constraint interview_configurations_check1 CHECK (status <> 'completed'::text OR completed_at IS NOT NULL);

alter table public.interview_configurations add constraint interview_configurations_check2 CHECK (status <> 'invalidated'::text OR invalidated_at IS NOT NULL);

alter table public.interview_configurations add constraint interview_configurations_question_count_check CHECK (question_count >= 0 AND question_count <= 10);

alter table public.interview_configurations add constraint interview_configurations_status_check CHECK (status = ANY (ARRAY['processing'::text, 'ready'::text, 'in_progress'::text, 'completed'::text, 'failed'::text, 'invalidated'::text]));

alter table public.interview_configurations add constraint interview_configurations_version_no_check CHECK (version_no > 0);

alter table public.interview_document_analyses add constraint interview_document_analyses_processing_status_check CHECK (processing_status = ANY (ARRAY['processing'::text, 'succeeded'::text, 'failed'::text, 'invalidated'::text]));

alter table public.interview_documents add constraint interview_documents_size_check CHECK (size_bytes IS NULL OR size_bytes >= 0);

alter table public.interview_documents add constraint interview_documents_status_check CHECK (processing_status = ANY (ARRAY['uploaded'::text, 'processing'::text, 'ready'::text, 'failed'::text]));

alter table public.interview_documents add constraint interview_documents_status_contract CHECK ((upload_status = ANY (ARRAY['processing'::text, 'succeeded'::text, 'failed'::text, 'deleting'::text, 'deleted'::text])) AND (analysis_status = ANY (ARRAY['pending'::text, 'processing'::text, 'succeeded'::text, 'failed'::text, 'invalidated'::text])) AND version_no > 0) NOT VALID;

alter table public.interview_documents add constraint interview_documents_type_check CHECK (document_type = ANY (ARRAY['resume'::text, 'portfolio'::text, 'cover_letter'::text]));

alter table public.interview_questions add constraint interview_questions_question_text_check CHECK (btrim(question_text) <> ''::text);

alter table public.interview_questions add constraint interview_questions_sequence_no_check CHECK (sequence_no >= 1 AND sequence_no <= 10);

alter table public.interview_setups add constraint interview_setups_progress_check CHECK (preparation_progress >= 0 AND preparation_progress <= 100);

alter table public.interview_setups add constraint interview_setups_status_check CHECK (status = ANY (ARRAY['draft'::text, 'analyzing'::text, 'ready'::text, 'failed'::text]));

alter table public.message_ai_processing add constraint message_ai_processing_attempt_count_check CHECK (attempt_count >= 0);

alter table public.message_ai_processing add constraint message_ai_processing_check CHECK (processing_status = 'succeeded'::text AND completed_at IS NOT NULL OR processing_status <> 'succeeded'::text);

alter table public.message_ai_processing add constraint message_ai_processing_processing_status_check CHECK (processing_status = ANY (ARRAY['processing'::text, 'succeeded'::text, 'failed'::text]));

alter table public.message_audio add constraint message_audio_duration_check CHECK (duration_ms IS NULL OR duration_ms >= 0);

alter table public.message_audio add constraint message_audio_status_check CHECK (generation_status = ANY (ARRAY['processing'::text, 'ready'::text, 'failed'::text]));

alter table public.message_audio add constraint message_audio_type_check CHECK (audio_type = ANY (ARRAY['user_recording'::text, 'persona_tts'::text]));

alter table public.message_emotion_analysis add constraint message_emotion_analysis_attempt_count_check CHECK (attempt_count >= 0);

alter table public.message_emotion_analysis add constraint message_emotion_analysis_check CHECK (processing_status <> 'succeeded'::text OR emotion_label IS NOT NULL AND reasoning IS NOT NULL);

alter table public.message_emotion_analysis add constraint message_emotion_analysis_emotion_label_check CHECK (emotion_label = ANY (ARRAY['neutral'::text, 'happy'::text, 'sad'::text, 'angry'::text, 'curious'::text, 'embarrassment'::text]));

alter table public.message_emotion_analysis add constraint message_emotion_analysis_processing_status_check CHECK (processing_status = ANY (ARRAY['processing'::text, 'succeeded'::text, 'failed'::text]));

alter table public.practice_rooms add constraint practice_rooms_interview_configuration_contract CHECK (practice_type = 'interview'::text AND interview_configuration_id IS NOT NULL OR practice_type <> 'interview'::text AND interview_configuration_id IS NULL) NOT VALID;

alter table public.practice_rooms add constraint practice_rooms_status_check CHECK (status = ANY (ARRAY['in_progress'::text, 'completed'::text, 'failed'::text, 'abandoned'::text]));

alter table public.practice_rooms add constraint practice_rooms_turn_count_check CHECK (turn_count >= 0);

alter table public.practice_rooms add constraint practice_rooms_type_check CHECK (practice_type = ANY (ARRAY['free_chat'::text, 'scenario'::text, 'interview'::text]));

alter table public.processing_jobs add constraint processing_jobs_attempt_check CHECK (transport_attempt_count >= 0 AND schema_repair_count >= 0 AND schema_repair_count <= 1);

alter table public.processing_jobs add constraint processing_jobs_job_type_check CHECK (job_type = ANY (ARRAY['conversation_text'::text, 'emotion_analysis'::text, 'tts_generation'::text, 'turn_feedback'::text, 'interview_document_analysis'::text, 'interview_configuration_generation'::text, 'session_result_generation'::text]));

alter table public.processing_jobs add constraint processing_jobs_progress_check CHECK (status <> 'processing'::text AND progress_stage IS NULL OR status = 'processing'::text AND (progress_stage IS NULL OR job_type = 'conversation_text'::text AND (progress_stage = ANY (ARRAY['context_preparing'::text, 'provider_processing'::text, 'saving_response'::text])) OR job_type = 'emotion_analysis'::text AND (progress_stage = ANY (ARRAY['provider_processing'::text, 'saving_analysis'::text])) OR job_type = 'tts_generation'::text AND (progress_stage = ANY (ARRAY['provider_processing'::text, 'storing_audio'::text])) OR job_type = 'turn_feedback'::text AND (progress_stage = ANY (ARRAY['provider_processing'::text, 'saving_feedback'::text])) OR job_type = 'interview_document_analysis'::text AND (progress_stage = ANY (ARRAY['extracting_text'::text, 'chunking'::text, 'embedding'::text, 'saving_analysis'::text])) OR job_type = 'interview_configuration_generation'::text AND (progress_stage = ANY (ARRAY['retrieving_evidence'::text, 'provider_processing'::text, 'saving_configuration'::text])) OR job_type = 'session_result_generation'::text AND (progress_stage = ANY (ARRAY['aggregating_evidence'::text, 'provider_processing'::text, 'saving_result'::text]))));

alter table public.processing_jobs add constraint processing_jobs_status_check CHECK (status = ANY (ARRAY['queued'::text, 'processing'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text]));

alter table public.processing_jobs add constraint processing_jobs_target_count_check CHECK (num_nonnulls(message_ai_processing_id, message_emotion_analysis_id, message_audio_id, turn_feedback_id, interview_document_analysis_id, interview_configuration_id, session_result_id) = 1);

alter table public.processing_jobs add constraint processing_jobs_terminal_shape_check CHECK ((status = ANY (ARRAY['succeeded'::text, 'failed'::text, 'cancelled'::text])) = (completed_at IS NOT NULL) AND (status <> 'processing'::text OR started_at IS NOT NULL) AND (status = 'failed'::text AND error_code IS NOT NULL AND error_retryable IS NOT NULL OR status <> 'failed'::text AND error_code IS NULL AND error_retryable IS NULL AND error_meta IS NULL) AND (error_meta IS NULL OR jsonb_typeof(error_meta) = 'object'::text));

alter table public.processing_jobs add constraint processing_jobs_type_target_check CHECK (job_type = 'conversation_text'::text AND message_ai_processing_id IS NOT NULL OR job_type = 'emotion_analysis'::text AND message_emotion_analysis_id IS NOT NULL OR job_type = 'tts_generation'::text AND message_audio_id IS NOT NULL OR job_type = 'turn_feedback'::text AND turn_feedback_id IS NOT NULL OR job_type = 'interview_document_analysis'::text AND interview_document_analysis_id IS NOT NULL OR job_type = 'interview_configuration_generation'::text AND interview_configuration_id IS NOT NULL OR job_type = 'session_result_generation'::text AND session_result_id IS NOT NULL);

alter table public.processing_jobs add constraint processing_jobs_units_check CHECK (completed_units IS NULL AND total_units IS NULL OR status = 'processing'::text AND completed_units >= 0 AND total_units > 0 AND completed_units <= total_units);

alter table public.processing_timeout_policies add constraint processing_timeout_policies_max_attempts_check CHECK (max_attempts > 0);

alter table public.processing_timeout_policies add constraint processing_timeout_policies_timeout_seconds_check CHECK (timeout_seconds > 0);

alter table public.profiles add constraint profiles_display_language_check CHECK (display_language = ANY (ARRAY['ko'::text, 'en'::text]));

alter table public.profiles add constraint profiles_onboarding_fields_contract CHECK (NOT onboarding_completed OR display_name IS NOT NULL AND btrim(display_name) <> ''::text AND birth_date IS NOT NULL AND gender IS NOT NULL AND btrim(gender) <> ''::text AND native_language IS NOT NULL AND btrim(native_language) <> ''::text AND (display_language = ANY (ARRAY['ko'::text, 'en'::text]))) NOT VALID;

alter table public.result_items add constraint result_items_type_check CHECK (item_type = ANY (ARRAY['strength'::text, 'improvement'::text]));

alter table public.room_messages add constraint room_messages_emotion_check CHECK (persona_emotion IS NULL OR (persona_emotion = ANY (ARRAY['neutral'::text, 'happy'::text, 'sad'::text, 'angry'::text, 'curious'::text, 'embarrassment'::text])));

alter table public.room_messages add constraint room_messages_input_mode_check CHECK (input_mode IS NULL OR (input_mode = ANY (ARRAY['text'::text, 'voice'::text])));

alter table public.room_messages add constraint room_messages_sender_check CHECK (sender_type = ANY (ARRAY['user'::text, 'persona'::text, 'system'::text]));

alter table public.room_messages add constraint room_messages_status_check CHECK (delivery_status = ANY (ARRAY['sending'::text, 'sent'::text, 'generating'::text, 'failed'::text]));

alter table public.scenarios add constraint scenarios_estimated_minutes_check CHECK (estimated_minutes IS NULL OR estimated_minutes > 0);

alter table public.scenarios add constraint scenarios_max_turns_check CHECK (max_turns IS NULL OR max_turns > 0);

alter table public.scenarios add constraint scenarios_practice_type_check CHECK (practice_type = ANY (ARRAY['free_chat'::text, 'scenario'::text, 'interview'::text]));

alter table public.session_results add constraint session_results_duration_check CHECK (duration_seconds IS NULL OR duration_seconds >= 0);

alter table public.session_results add constraint session_results_no_hiring_decision CHECK (interview_outcome IS NULL OR (lower(interview_outcome) <> ALL (ARRAY['pass'::text, 'fail'::text, 'passed'::text, 'failed'::text, '합격'::text, '불합격'::text]))) NOT VALID;

alter table public.session_results add constraint session_results_outcome_check CHECK (interview_outcome IS NULL OR (interview_outcome = ANY (ARRAY['pass'::text, 'borderline'::text, 'needs_practice'::text])));

alter table public.session_results add constraint session_results_score_check CHECK (overall_score IS NULL OR overall_score >= 0::numeric AND overall_score <= 100::numeric);

alter table public.session_results add constraint session_results_status_contract CHECK ((result_status = ANY (ARRAY['processing'::text, 'partial'::text, 'succeeded'::text, 'failed'::text])) AND attempt_no > 0) NOT VALID;

alter table public.storage_deletion_jobs add constraint storage_deletion_jobs_attempt_count_check CHECK (attempt_count >= 0);

alter table public.storage_deletion_jobs add constraint storage_deletion_jobs_deletion_status_check CHECK (deletion_status = ANY (ARRAY['pending'::text, 'processing'::text, 'succeeded'::text, 'failed'::text]));

alter table public.storage_deletion_jobs add constraint storage_deletion_jobs_retry_contract CHECK (max_attempts > 0 AND attempt_count >= 0 AND attempt_count <= max_attempts AND (locked_at IS NULL AND locked_by IS NULL AND lock_expires_at IS NULL OR locked_at IS NOT NULL AND locked_by IS NOT NULL AND lock_expires_at IS NOT NULL)) NOT VALID;

alter table public.turn_feedback add constraint turn_feedback_duration_check CHECK (source_duration_ms IS NULL OR source_duration_ms >= 0);

alter table public.turn_feedback add constraint turn_feedback_overall_score_range CHECK (overall_score IS NULL OR overall_score >= 0::numeric AND overall_score <= 100::numeric AND overall_score = trunc(overall_score)) NOT VALID;

alter table public.turn_feedback add constraint turn_feedback_score_check CHECK (overall_score IS NULL OR overall_score >= 0::numeric AND overall_score <= 100::numeric);

alter table public.turn_feedback add constraint turn_feedback_status_check CHECK (analysis_status = ANY (ARRAY['processing'::text, 'ready'::text, 'partial'::text, 'failed'::text]));

-- Foreign keys

alter table public.feedback_emotions add constraint feedback_emotions_feedback_id_fkey FOREIGN KEY (feedback_id) REFERENCES turn_feedback(id) ON DELETE CASCADE;

alter table public.feedback_scores add constraint feedback_scores_feedback_id_fkey FOREIGN KEY (feedback_id) REFERENCES turn_feedback(id) ON DELETE CASCADE;

alter table public.idempotency_records add constraint idempotency_records_processing_job_id_fkey FOREIGN KEY (processing_job_id) REFERENCES processing_jobs(id) ON DELETE SET NULL;

alter table public.idempotency_records add constraint idempotency_records_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.interview_answers add constraint interview_answers_message_id_fkey FOREIGN KEY (message_id) REFERENCES room_messages(id) ON DELETE CASCADE;

alter table public.interview_answers add constraint interview_answers_question_id_fkey FOREIGN KEY (question_id) REFERENCES interview_questions(id) ON DELETE CASCADE;

alter table public.interview_answers add constraint interview_answers_room_id_fkey FOREIGN KEY (room_id) REFERENCES practice_rooms(id) ON DELETE CASCADE;

alter table public.interview_configurations add constraint interview_configurations_setup_id_fkey FOREIGN KEY (setup_id) REFERENCES interview_setups(id) ON DELETE CASCADE;

alter table public.interview_configurations add constraint interview_configurations_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.interview_document_analyses add constraint interview_document_analyses_document_id_fkey FOREIGN KEY (document_id) REFERENCES interview_documents(id) ON DELETE RESTRICT;

alter table public.interview_document_analyses add constraint interview_document_analyses_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.interview_documents add constraint interview_documents_replaced_document_id_fkey FOREIGN KEY (replaced_document_id) REFERENCES interview_documents(id) ON DELETE SET NULL;

alter table public.interview_documents add constraint interview_documents_setup_id_fkey FOREIGN KEY (setup_id) REFERENCES interview_setups(id) ON DELETE CASCADE;

alter table public.interview_documents add constraint interview_documents_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.interview_questions add constraint interview_questions_configuration_id_fkey FOREIGN KEY (configuration_id) REFERENCES interview_configurations(id) ON DELETE CASCADE;

alter table public.interview_setups add constraint interview_setups_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.message_ai_processing add constraint message_ai_processing_message_id_fkey FOREIGN KEY (message_id) REFERENCES room_messages(id) ON DELETE CASCADE;

alter table public.message_audio add constraint message_audio_message_id_fkey FOREIGN KEY (message_id) REFERENCES room_messages(id) ON DELETE CASCADE;

alter table public.message_audio add constraint message_audio_replacement_for_id_fkey FOREIGN KEY (replacement_for_id) REFERENCES message_audio(id) ON DELETE SET NULL;

alter table public.message_emotion_analysis add constraint message_emotion_analysis_message_id_fkey FOREIGN KEY (message_id) REFERENCES room_messages(id) ON DELETE CASCADE;

alter table public.persona_scenarios add constraint persona_scenarios_persona_id_fkey FOREIGN KEY (persona_id) REFERENCES personas(id) ON DELETE CASCADE;

alter table public.persona_scenarios add constraint persona_scenarios_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE;

alter table public.practice_rooms add constraint practice_rooms_interview_configuration_id_fkey FOREIGN KEY (interview_configuration_id) REFERENCES interview_configurations(id) ON DELETE RESTRICT;

alter table public.practice_rooms add constraint practice_rooms_interview_setup_id_fkey FOREIGN KEY (interview_setup_id) REFERENCES interview_setups(id) ON DELETE SET NULL;

alter table public.practice_rooms add constraint practice_rooms_persona_id_fkey FOREIGN KEY (persona_id) REFERENCES personas(id) ON DELETE SET NULL;

alter table public.practice_rooms add constraint practice_rooms_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE SET NULL;

alter table public.practice_rooms add constraint practice_rooms_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.processing_jobs add constraint processing_jobs_interview_configuration_id_fkey FOREIGN KEY (interview_configuration_id) REFERENCES interview_configurations(id) ON DELETE CASCADE;

alter table public.processing_jobs add constraint processing_jobs_interview_document_analysis_id_fkey FOREIGN KEY (interview_document_analysis_id) REFERENCES interview_document_analyses(id) ON DELETE CASCADE;

alter table public.processing_jobs add constraint processing_jobs_message_ai_processing_id_fkey FOREIGN KEY (message_ai_processing_id) REFERENCES message_ai_processing(id) ON DELETE CASCADE;

alter table public.processing_jobs add constraint processing_jobs_message_audio_id_fkey FOREIGN KEY (message_audio_id) REFERENCES message_audio(id) ON DELETE CASCADE;

alter table public.processing_jobs add constraint processing_jobs_message_emotion_analysis_id_fkey FOREIGN KEY (message_emotion_analysis_id) REFERENCES message_emotion_analysis(id) ON DELETE CASCADE;

alter table public.processing_jobs add constraint processing_jobs_session_result_id_fkey FOREIGN KEY (session_result_id) REFERENCES session_results(id) ON DELETE CASCADE;

alter table public.processing_jobs add constraint processing_jobs_turn_feedback_id_fkey FOREIGN KEY (turn_feedback_id) REFERENCES turn_feedback(id) ON DELETE CASCADE;

alter table public.processing_jobs add constraint processing_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.profiles add constraint profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.result_items add constraint result_items_result_id_fkey FOREIGN KEY (result_id) REFERENCES session_results(id) ON DELETE CASCADE;

alter table public.result_items add constraint result_items_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES interview_documents(id) ON DELETE SET NULL;

alter table public.room_contexts add constraint room_contexts_room_id_fkey FOREIGN KEY (room_id) REFERENCES practice_rooms(id) ON DELETE CASCADE;

alter table public.room_contexts add constraint room_contexts_summarized_through_message_id_fkey FOREIGN KEY (summarized_through_message_id) REFERENCES room_messages(id) ON DELETE SET NULL;

alter table public.room_messages add constraint room_messages_reply_to_message_id_fkey FOREIGN KEY (reply_to_message_id) REFERENCES room_messages(id) ON DELETE CASCADE;

alter table public.room_messages add constraint room_messages_room_id_fkey FOREIGN KEY (room_id) REFERENCES practice_rooms(id) ON DELETE CASCADE;

alter table public.room_success_condition_progress add constraint room_success_condition_progress_condition_id_fkey FOREIGN KEY (condition_id) REFERENCES scenario_success_conditions(id) ON DELETE RESTRICT;

alter table public.room_success_condition_progress add constraint room_success_condition_progress_evidence_message_id_fkey FOREIGN KEY (evidence_message_id) REFERENCES room_messages(id) ON DELETE SET NULL;

alter table public.room_success_condition_progress add constraint room_success_condition_progress_room_id_fkey FOREIGN KEY (room_id) REFERENCES practice_rooms(id) ON DELETE CASCADE;

alter table public.scenario_success_conditions add constraint scenario_success_conditions_scenario_id_fkey FOREIGN KEY (scenario_id) REFERENCES scenarios(id) ON DELETE CASCADE;

alter table public.session_results add constraint session_results_room_id_fkey FOREIGN KEY (room_id) REFERENCES practice_rooms(id) ON DELETE SET NULL;

alter table public.session_results add constraint session_results_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.storage_deletion_jobs add constraint storage_deletion_jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

alter table public.turn_feedback add constraint turn_feedback_message_id_fkey FOREIGN KEY (message_id) REFERENCES room_messages(id) ON DELETE CASCADE;

alter table public.user_consents add constraint user_consents_user_id_fkey FOREIGN KEY (user_id) REFERENCES auth.users(id) ON DELETE CASCADE;

-- Indexes

CREATE UNIQUE INDEX consent_policies_one_active_version_idx ON consent_policies USING btree (consent_type) WHERE is_active;

CREATE INDEX feedback_emotions_feedback_idx ON feedback_emotions USING btree (feedback_id);

CREATE INDEX feedback_scores_feedback_idx ON feedback_scores USING btree (feedback_id);

CREATE INDEX idempotency_records_expiry_idx ON idempotency_records USING btree (expires_at) WHERE state = ANY (ARRAY['completed'::text, 'failed'::text]);

CREATE INDEX idempotency_records_job_idx ON idempotency_records USING btree (processing_job_id) WHERE processing_job_id IS NOT NULL;

CREATE INDEX idempotency_records_lease_idx ON idempotency_records USING btree (lease_expires_at) WHERE state = 'in_progress'::text;

CREATE UNIQUE INDEX interview_answers_one_current_idx ON interview_answers USING btree (question_id) WHERE is_current;

CREATE INDEX interview_answers_room_submitted_idx ON interview_answers USING btree (room_id, submitted_at);

CREATE UNIQUE INDEX interview_configurations_one_active_idx ON interview_configurations USING btree (setup_id) WHERE status = ANY (ARRAY['processing'::text, 'ready'::text, 'in_progress'::text]);

CREATE INDEX interview_configurations_timeout_idx ON interview_configurations USING btree (status, deadline_at) WHERE status = 'processing'::text;

CREATE INDEX interview_document_analyses_timeout_idx ON interview_document_analyses USING btree (processing_status, deadline_at) WHERE processing_status = 'processing'::text;

CREATE INDEX interview_document_analyses_user_started_idx ON interview_document_analyses USING btree (user_id, started_at DESC);

CREATE UNIQUE INDEX interview_documents_one_current_type_idx ON interview_documents USING btree (setup_id, document_type) WHERE is_current AND deleted_at IS NULL;

CREATE INDEX interview_documents_setup_idx ON interview_documents USING btree (setup_id);

CREATE INDEX interview_documents_user_idx ON interview_documents USING btree (user_id);

CREATE INDEX interview_questions_configuration_sequence_idx ON interview_questions USING btree (configuration_id, sequence_no);

CREATE INDEX interview_setups_user_created_idx ON interview_setups USING btree (user_id, created_at DESC);

CREATE INDEX message_ai_processing_timeout_idx ON message_ai_processing USING btree (processing_status, deadline_at) WHERE processing_status = 'processing'::text;

CREATE INDEX message_audio_message_idx ON message_audio USING btree (message_id);

CREATE UNIQUE INDEX message_audio_one_current_type_idx ON message_audio USING btree (message_id, audio_type) WHERE is_current;

CREATE INDEX message_audio_timeout_idx ON message_audio USING btree (generation_status, deadline_at) WHERE generation_status = 'processing'::text;

CREATE INDEX message_emotion_analysis_timeout_idx ON message_emotion_analysis USING btree (processing_status, deadline_at) WHERE processing_status = 'processing'::text;

CREATE INDEX personas_active_sort_idx ON personas USING btree (is_active, sort_order);

CREATE UNIQUE INDEX practice_rooms_one_active_free_chat_idx ON practice_rooms USING btree (user_id, persona_id) WHERE practice_type = 'free_chat'::text AND status = 'in_progress'::text;

CREATE UNIQUE INDEX practice_rooms_one_active_interview_idx ON practice_rooms USING btree (user_id, interview_configuration_id) WHERE practice_type = 'interview'::text AND status = 'in_progress'::text;

CREATE UNIQUE INDEX practice_rooms_one_active_scenario_idx ON practice_rooms USING btree (user_id, persona_id, scenario_id) WHERE practice_type = 'scenario'::text AND status = 'in_progress'::text;

CREATE INDEX practice_rooms_user_status_idx ON practice_rooms USING btree (user_id, status);

CREATE INDEX practice_rooms_user_updated_idx ON practice_rooms USING btree (user_id, updated_at DESC);

CREATE UNIQUE INDEX processing_jobs_active_ai_idx ON processing_jobs USING btree (message_ai_processing_id) WHERE (status = ANY (ARRAY['queued'::text, 'processing'::text])) AND message_ai_processing_id IS NOT NULL;

CREATE UNIQUE INDEX processing_jobs_active_audio_idx ON processing_jobs USING btree (message_audio_id) WHERE (status = ANY (ARRAY['queued'::text, 'processing'::text])) AND message_audio_id IS NOT NULL;

CREATE UNIQUE INDEX processing_jobs_active_configuration_idx ON processing_jobs USING btree (interview_configuration_id) WHERE (status = ANY (ARRAY['queued'::text, 'processing'::text])) AND interview_configuration_id IS NOT NULL;

CREATE UNIQUE INDEX processing_jobs_active_document_idx ON processing_jobs USING btree (interview_document_analysis_id) WHERE (status = ANY (ARRAY['queued'::text, 'processing'::text])) AND interview_document_analysis_id IS NOT NULL;

CREATE UNIQUE INDEX processing_jobs_active_emotion_idx ON processing_jobs USING btree (message_emotion_analysis_id) WHERE (status = ANY (ARRAY['queued'::text, 'processing'::text])) AND message_emotion_analysis_id IS NOT NULL;

CREATE UNIQUE INDEX processing_jobs_active_feedback_idx ON processing_jobs USING btree (turn_feedback_id) WHERE (status = ANY (ARRAY['queued'::text, 'processing'::text])) AND turn_feedback_id IS NOT NULL;

CREATE UNIQUE INDEX processing_jobs_active_result_idx ON processing_jobs USING btree (session_result_id) WHERE (status = ANY (ARRAY['queued'::text, 'processing'::text])) AND session_result_id IS NOT NULL;

CREATE INDEX processing_jobs_claim_idx ON processing_jobs USING btree (status, next_attempt_at, created_at) WHERE status = 'queued'::text;

CREATE INDEX processing_jobs_deadline_idx ON processing_jobs USING btree (deadline_at) WHERE status = ANY (ARRAY['queued'::text, 'processing'::text]);

CREATE INDEX processing_jobs_owner_created_idx ON processing_jobs USING btree (user_id, created_at DESC, id DESC);

CREATE INDEX result_items_result_sort_idx ON result_items USING btree (result_id, sort_order);

CREATE INDEX room_messages_room_sequence_idx ON room_messages USING btree (room_id, sequence_no);

CREATE INDEX scenarios_active_type_sort_idx ON scenarios USING btree (is_active, practice_type, sort_order);

CREATE INDEX session_results_user_created_idx ON session_results USING btree (user_id, created_at DESC);

CREATE INDEX storage_deletion_jobs_claim_idx ON storage_deletion_jobs USING btree (deletion_status, next_attempt_at) WHERE deletion_status = ANY (ARRAY['pending'::text, 'failed'::text]);

CREATE INDEX storage_deletion_jobs_status_created_idx ON storage_deletion_jobs USING btree (deletion_status, created_at);

CREATE INDEX turn_feedback_timeout_idx ON turn_feedback USING btree (analysis_status, deadline_at) WHERE analysis_status = 'processing'::text;

CREATE INDEX user_consents_user_idx ON user_consents USING btree (user_id);

-- Comments

comment on table public.feedback_emotions is '[발화 피드백] 발화에서 AI가 추정한 감정 비율과 상대에게 들릴 수 있는 인상을 저장합니다.';

comment on table public.feedback_scores is '[발화 피드백] 높임말, 예의와 배려, 상황 적합성, 자연스러움의 항목별 점수와 잘한 점·제안·추천 표현을 저장합니다.';

comment on table public.interview_documents is '[면접 준비] 이력서·포트폴리오·자기소개서의 파일 메타데이터, Storage 경로, 처리 상태와 추출 결과를 저장합니다. 파일 원본 자체는 Storage에 보관합니다.';

comment on table public.interview_setups is '[면접 준비] 사용자가 입력한 희망 직무, 지원 유형과 맞춤 면접 구성 진행 상태를 저장합니다.';

comment on table public.message_audio is '[대화] 메시지에 연결된 사용자 녹음 또는 AI TTS 음성의 Storage 경로, 길이와 생성 상태를 관리합니다.';

comment on table public.persona_scenarios is '[연습 카탈로그] 실제 선택 가능한 페르소나와 시나리오 조합 및 두 대상의 관계 라벨을 연결하는 테이블입니다.';

comment on table public.personas is '[연습 카탈로그] 대화 연습에서 선택할 수 있는 AI 상대의 이름, 역할, 소개, 이미지 키와 노출 순서를 관리하는 마스터 테이블입니다.';

comment on table public.practice_rooms is '[대화] 일반 대화 또는 면접 연습 한 회차를 나타냅니다. 사용자, 페르소나, 시나리오, 목표, 진행 상태, 턴 수와 시작·완료 시점을 관리합니다.';

comment on table public.profiles is '[계정·프로필] Supabase Auth 사용자와 1:1로 연결되는 서비스 프로필입니다. 이름, 생년월일, 성별, 모국어, 표시 언어와 온보딩 완료 여부를 저장합니다.';

comment on table public.result_items is '[결과·복습] 최종 결과에서 보여줄 잘한 점과 개선할 점, 원래 표현, 추천 표현, 설명 및 근거 자료 연결을 저장합니다.';

comment on table public.room_messages is '[대화] 대화방 안의 사용자·AI·시스템 메시지를 순서대로 저장합니다. 텍스트/음성 입력 방식, 전송 상태, 전사 확인 여부와 페르소나 감정도 기록합니다.';

comment on table public.scenarios is '[연습 카탈로그] 자유 대화·상황 대화·면접 연습의 제목, 목표, 장소, 난이도, 예상 시간, 시작 문장과 턴 제한을 관리합니다.';

comment on table public.session_results is '[결과·복습] 대화방 한 회차의 최종 종합 점수, 요약, 목표 달성 여부, 면접 예상 결과와 진행 시간을 저장합니다.';

comment on table public.turn_feedback is '[발화 피드백] 사용자 발화 한 건에 대한 종합 점수, 요약, 분석 상태와 음성 길이를 저장하는 피드백 헤더입니다.';

comment on table public.user_consents is '[계정·프로필] 사용자가 동의한 약관·개인정보 처리방침의 종류, 버전, 동의·철회 시점을 기록합니다.';

-- Functions

CREATE OR REPLACE FUNCTION public.handle_new_user()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
begin
  insert into public.profiles (id, display_name)
  values (new.id, nullif(new.raw_user_meta_data ->> 'name', ''))
  on conflict (id) do nothing;
  return new;
end;
$function$
;

CREATE OR REPLACE FUNCTION public.purge_expired_idempotency_records(p_batch_size integer)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare v_count integer;
begin
  if p_batch_size is null or p_batch_size<=0 then raise exception using errcode='22023',message='positive batch size required'; end if;
  with candidates as (select id from public.idempotency_records where state in ('completed','failed') and expires_at<=now() order by expires_at,id for update skip locked limit p_batch_size), deleted as (delete from public.idempotency_records r using candidates c where r.id=c.id returning 1) select count(*) into v_count from deleted;
  return v_count;
end $function$
;

CREATE OR REPLACE FUNCTION public.recalculate_turn_feedback_overall_score()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
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
    and category in ('honorifics', 'consideration', 'context_fit', 'naturalness');

  update public.turn_feedback
  set overall_score = case when category_count = 4 then total_score else null end,
      updated_at = now()
  where id = target_feedback_id;

  return coalesce(new, old);
end;
$function$
;

CREATE OR REPLACE FUNCTION public.set_architecture_record_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public', 'pg_temp'
AS $function$ begin new.updated_at=now(); return new; end $function$
;

CREATE OR REPLACE FUNCTION public.set_updated_at()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  new.updated_at = now();
  return new;
end;
$function$
;

CREATE OR REPLACE FUNCTION public.synchronize_interview_question_count()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
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
$function$
;

CREATE OR REPLACE FUNCTION public.validate_feedback_emotion_limit()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
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
$function$
;

CREATE OR REPLACE FUNCTION public.validate_idempotency_job_owner()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
begin if new.processing_job_id is not null and not exists(select 1 from public.processing_jobs j where j.id=new.processing_job_id and j.user_id=new.user_id) then raise exception using errcode='23514',message='idempotency job owner mismatch'; end if; return new; end $function$
;

CREATE OR REPLACE FUNCTION public.validate_idempotency_transition()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare v_only_job_unlink boolean;
begin
  v_only_job_unlink:=old.processing_job_id is not null and new.processing_job_id is null and new.state=old.state and (to_jsonb(new)-'processing_job_id'-'updated_at')=(to_jsonb(old)-'processing_job_id'-'updated_at');
  if old.state='completed' then if v_only_job_unlink then return new; end if; raise exception using errcode='23514',message='completed idempotency record is immutable'; end if;
  if old.state='failed' and not old.error_retryable then if v_only_job_unlink then return new; end if; raise exception using errcode='23514',message='terminal idempotency failure is immutable'; end if;
  if new.state=old.state then return new; end if;
  if old.state='in_progress' and new.state not in ('completed','failed') then raise exception using errcode='23514',message='invalid idempotency transition'; end if;
  if old.state='failed' and old.error_retryable and new.state<>'in_progress' then raise exception using errcode='23514',message='retryable failure requires CAS recovery claim'; end if;
  return new;
end $function$
;

CREATE OR REPLACE FUNCTION public.validate_interview_answer_message()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
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
$function$
;

CREATE OR REPLACE FUNCTION public.validate_practice_room_start()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
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
$function$
;

CREATE OR REPLACE FUNCTION public.validate_processing_job_domain_state()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
end $function$
;

CREATE OR REPLACE FUNCTION public.validate_processing_job_owner_target()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
end $function$
;

CREATE OR REPLACE FUNCTION public.validate_processing_job_transition()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'public', 'pg_temp'
AS $function$
begin
  if old.status in ('succeeded','failed','cancelled') then raise exception using errcode='23514',message='terminal processing job is immutable'; end if;
  if new.status=old.status then return new; end if;
  if old.status='queued' and new.status not in ('processing','failed','cancelled') then raise exception using errcode='23514',message='invalid queued job transition'; end if;
  if old.status='processing' and new.status not in ('queued','succeeded','failed','cancelled') then raise exception using errcode='23514',message='invalid processing job transition'; end if;
  return new;
end $function$
;

CREATE OR REPLACE FUNCTION public.validate_profile_onboarding_completion()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
$function$
;

-- Triggers

CREATE TRIGGER validate_feedback_emotion_limit_trigger BEFORE INSERT OR UPDATE OF feedback_id ON feedback_emotions FOR EACH ROW EXECUTE FUNCTION validate_feedback_emotion_limit();

CREATE TRIGGER feedback_scores_recalculate_overall_trigger AFTER INSERT OR DELETE OR UPDATE ON feedback_scores FOR EACH ROW EXECUTE FUNCTION recalculate_turn_feedback_overall_score();

CREATE TRIGGER idempotency_records_job_owner_trigger BEFORE INSERT OR UPDATE OF user_id, processing_job_id ON idempotency_records FOR EACH ROW EXECUTE FUNCTION validate_idempotency_job_owner();

CREATE TRIGGER idempotency_records_transition_trigger BEFORE UPDATE ON idempotency_records FOR EACH ROW EXECUTE FUNCTION validate_idempotency_transition();

CREATE TRIGGER idempotency_records_updated_at_trigger BEFORE UPDATE ON idempotency_records FOR EACH ROW EXECUTE FUNCTION set_architecture_record_updated_at();

CREATE TRIGGER validate_interview_answer_message_trigger BEFORE INSERT OR UPDATE OF question_id, room_id, message_id ON interview_answers FOR EACH ROW EXECUTE FUNCTION validate_interview_answer_message();

CREATE TRIGGER synchronize_interview_question_count_trigger AFTER INSERT OR DELETE OR UPDATE OF configuration_id ON interview_questions FOR EACH ROW EXECUTE FUNCTION synchronize_interview_question_count();

CREATE TRIGGER interview_setups_set_updated_at BEFORE UPDATE ON interview_setups FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER practice_rooms_set_updated_at BEFORE UPDATE ON practice_rooms FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER validate_practice_room_start_trigger BEFORE INSERT OR UPDATE OF status, scenario_id ON practice_rooms FOR EACH ROW EXECUTE FUNCTION validate_practice_room_start();

CREATE CONSTRAINT TRIGGER processing_jobs_domain_state_trigger AFTER INSERT OR UPDATE ON processing_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_processing_job_domain_state();

CREATE TRIGGER processing_jobs_owner_target_trigger BEFORE INSERT OR UPDATE OF user_id, job_type, message_ai_processing_id, message_emotion_analysis_id, message_audio_id, turn_feedback_id, interview_document_analysis_id, interview_configuration_id, session_result_id ON processing_jobs FOR EACH ROW EXECUTE FUNCTION validate_processing_job_owner_target();

CREATE TRIGGER processing_jobs_transition_trigger BEFORE UPDATE ON processing_jobs FOR EACH ROW EXECUTE FUNCTION validate_processing_job_transition();

CREATE TRIGGER processing_jobs_updated_at_trigger BEFORE UPDATE ON processing_jobs FOR EACH ROW EXECUTE FUNCTION set_architecture_record_updated_at();

CREATE TRIGGER profiles_set_updated_at BEFORE UPDATE ON profiles FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER validate_profile_onboarding_completion_trigger BEFORE INSERT OR UPDATE OF onboarding_completed, display_name, birth_date, gender, native_language, display_language ON profiles FOR EACH ROW EXECUTE FUNCTION validate_profile_onboarding_completion();

-- Row-level security

alter table public.consent_policies enable row level security;

alter table public.feedback_emotions enable row level security;

alter table public.feedback_scores enable row level security;

alter table public.idempotency_records enable row level security;

alter table public.interview_answers enable row level security;

alter table public.interview_configurations enable row level security;

alter table public.interview_document_analyses enable row level security;

alter table public.interview_documents enable row level security;

alter table public.interview_questions enable row level security;

alter table public.interview_setups enable row level security;

alter table public.message_ai_processing enable row level security;

alter table public.message_audio enable row level security;

alter table public.message_emotion_analysis enable row level security;

alter table public.persona_scenarios enable row level security;

alter table public.personas enable row level security;

alter table public.practice_rooms enable row level security;

alter table public.processing_jobs enable row level security;

alter table public.processing_timeout_policies enable row level security;

alter table public.profiles enable row level security;

alter table public.result_items enable row level security;

alter table public.room_contexts enable row level security;

alter table public.room_messages enable row level security;

alter table public.room_success_condition_progress enable row level security;

alter table public.scenario_success_conditions enable row level security;

alter table public.scenarios enable row level security;

alter table public.session_results enable row level security;

alter table public.storage_deletion_jobs enable row level security;

alter table public.turn_feedback enable row level security;

alter table public.user_consents enable row level security;

-- RLS policies

create policy consent_policies_authenticated_read on public.consent_policies as permissive for select to authenticated using (true);

create policy feedback_emotions_own_feedback on public.feedback_emotions as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM ((turn_feedback f
     JOIN room_messages m ON ((m.id = f.message_id)))
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((f.id = feedback_emotions.feedback_id) AND (r.user_id = ( SELECT auth.uid() AS uid)))))) with check ((EXISTS ( SELECT 1
   FROM ((turn_feedback f
     JOIN room_messages m ON ((m.id = f.message_id)))
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((f.id = feedback_emotions.feedback_id) AND (r.user_id = ( SELECT auth.uid() AS uid))))));

create policy feedback_scores_own_feedback on public.feedback_scores as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM ((turn_feedback f
     JOIN room_messages m ON ((m.id = f.message_id)))
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((f.id = feedback_scores.feedback_id) AND (r.user_id = ( SELECT auth.uid() AS uid)))))) with check ((EXISTS ( SELECT 1
   FROM ((turn_feedback f
     JOIN room_messages m ON ((m.id = f.message_id)))
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((f.id = feedback_scores.feedback_id) AND (r.user_id = ( SELECT auth.uid() AS uid))))));

create policy interview_answers_own_configuration on public.interview_answers as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM practice_rooms r
  WHERE ((r.id = interview_answers.room_id) AND (r.user_id = auth.uid()))))) with check ((EXISTS ( SELECT 1
   FROM practice_rooms r
  WHERE ((r.id = interview_answers.room_id) AND (r.user_id = auth.uid())))));

create policy interview_configurations_own_all on public.interview_configurations as permissive for all to authenticated using ((user_id = auth.uid())) with check ((user_id = auth.uid()));

create policy interview_document_analyses_own_all on public.interview_document_analyses as permissive for all to authenticated using ((user_id = auth.uid())) with check ((user_id = auth.uid()));

create policy interview_documents_own_all on public.interview_documents as permissive for all to authenticated using ((( SELECT auth.uid() AS uid) = user_id)) with check (((( SELECT auth.uid() AS uid) = user_id) AND (EXISTS ( SELECT 1
   FROM interview_setups s
  WHERE ((s.id = interview_documents.setup_id) AND (s.user_id = ( SELECT auth.uid() AS uid)))))));

create policy interview_questions_own_configuration on public.interview_questions as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM interview_configurations c
  WHERE ((c.id = interview_questions.configuration_id) AND (c.user_id = auth.uid()))))) with check ((EXISTS ( SELECT 1
   FROM interview_configurations c
  WHERE ((c.id = interview_questions.configuration_id) AND (c.user_id = auth.uid())))));

create policy interview_setups_own_all on public.interview_setups as permissive for all to authenticated using ((( SELECT auth.uid() AS uid) = user_id)) with check ((( SELECT auth.uid() AS uid) = user_id));

create policy message_ai_processing_own_room on public.message_ai_processing as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM (room_messages m
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((m.id = message_ai_processing.message_id) AND (r.user_id = auth.uid()))))) with check ((EXISTS ( SELECT 1
   FROM (room_messages m
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((m.id = message_ai_processing.message_id) AND (r.user_id = auth.uid())))));

create policy message_audio_own_room on public.message_audio as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM (room_messages m
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((m.id = message_audio.message_id) AND (r.user_id = ( SELECT auth.uid() AS uid)))))) with check ((EXISTS ( SELECT 1
   FROM (room_messages m
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((m.id = message_audio.message_id) AND (r.user_id = ( SELECT auth.uid() AS uid))))));

create policy message_emotion_analysis_own_room on public.message_emotion_analysis as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM (room_messages m
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((m.id = message_emotion_analysis.message_id) AND (r.user_id = auth.uid()))))) with check ((EXISTS ( SELECT 1
   FROM (room_messages m
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((m.id = message_emotion_analysis.message_id) AND (r.user_id = auth.uid())))));

create policy persona_scenarios_authenticated_read on public.persona_scenarios as permissive for select to authenticated using (true);

create policy personas_authenticated_read on public.personas as permissive for select to authenticated using (true);

create policy practice_rooms_own_all on public.practice_rooms as permissive for all to authenticated using ((( SELECT auth.uid() AS uid) = user_id)) with check ((( SELECT auth.uid() AS uid) = user_id));

create policy processing_jobs_own_read on public.processing_jobs as permissive for select to authenticated using ((user_id = auth.uid()));

create policy profiles_own_all on public.profiles as permissive for all to authenticated using ((( SELECT auth.uid() AS uid) = id)) with check ((( SELECT auth.uid() AS uid) = id));

create policy result_items_own_user_result on public.result_items as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM session_results r
  WHERE ((r.id = result_items.result_id) AND (r.user_id = auth.uid()))))) with check ((EXISTS ( SELECT 1
   FROM session_results r
  WHERE ((r.id = result_items.result_id) AND (r.user_id = auth.uid())))));

create policy room_contexts_own_room on public.room_contexts as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM practice_rooms r
  WHERE ((r.id = room_contexts.room_id) AND (r.user_id = auth.uid()))))) with check ((EXISTS ( SELECT 1
   FROM practice_rooms r
  WHERE ((r.id = room_contexts.room_id) AND (r.user_id = auth.uid())))));

create policy room_messages_own_room on public.room_messages as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM practice_rooms r
  WHERE ((r.id = room_messages.room_id) AND (r.user_id = ( SELECT auth.uid() AS uid)))))) with check ((EXISTS ( SELECT 1
   FROM practice_rooms r
  WHERE ((r.id = room_messages.room_id) AND (r.user_id = ( SELECT auth.uid() AS uid))))));

create policy room_success_condition_progress_own_room on public.room_success_condition_progress as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM practice_rooms r
  WHERE ((r.id = room_success_condition_progress.room_id) AND (r.user_id = auth.uid()))))) with check ((EXISTS ( SELECT 1
   FROM practice_rooms r
  WHERE ((r.id = room_success_condition_progress.room_id) AND (r.user_id = auth.uid())))));

create policy scenario_success_conditions_authenticated_read on public.scenario_success_conditions as permissive for select to authenticated using (true);

create policy scenarios_authenticated_read on public.scenarios as permissive for select to authenticated using (true);

create policy session_results_own_user on public.session_results as permissive for all to authenticated using ((user_id = auth.uid())) with check ((user_id = auth.uid()));

create policy storage_deletion_jobs_own_read on public.storage_deletion_jobs as permissive for select to authenticated using ((user_id = auth.uid()));

create policy turn_feedback_own_room on public.turn_feedback as permissive for all to authenticated using ((EXISTS ( SELECT 1
   FROM (room_messages m
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((m.id = turn_feedback.message_id) AND (r.user_id = ( SELECT auth.uid() AS uid)))))) with check ((EXISTS ( SELECT 1
   FROM (room_messages m
     JOIN practice_rooms r ON ((r.id = m.room_id)))
  WHERE ((m.id = turn_feedback.message_id) AND (r.user_id = ( SELECT auth.uid() AS uid))))));

create policy user_consents_own_all on public.user_consents as permissive for all to authenticated using ((( SELECT auth.uid() AS uid) = user_id)) with check ((( SELECT auth.uid() AS uid) = user_id));

-- Table grants

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.consent_policies to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.consent_policies to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.consent_policies to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.feedback_emotions to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.feedback_emotions to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.feedback_scores to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.feedback_scores to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.idempotency_records to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_answers to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_answers to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_answers to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_configurations to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_configurations to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_configurations to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_document_analyses to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_document_analyses to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_document_analyses to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_documents to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_documents to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_questions to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_questions to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_questions to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_setups to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.interview_setups to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.message_ai_processing to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.message_ai_processing to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.message_ai_processing to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.message_audio to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.message_audio to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.message_emotion_analysis to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.message_emotion_analysis to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.message_emotion_analysis to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.persona_scenarios to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.persona_scenarios to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.personas to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.personas to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.practice_rooms to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.practice_rooms to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.processing_jobs to service_role;

grant MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE on table public.processing_jobs to anon;

grant MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE on table public.processing_jobs to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.processing_timeout_policies to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.processing_timeout_policies to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.processing_timeout_policies to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.profiles to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.profiles to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.result_items to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.result_items to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.room_contexts to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.room_contexts to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.room_contexts to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.room_messages to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.room_messages to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.room_success_condition_progress to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.room_success_condition_progress to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.room_success_condition_progress to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.scenario_success_conditions to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.scenario_success_conditions to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.scenario_success_conditions to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.scenarios to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.scenarios to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.session_results to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.session_results to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.storage_deletion_jobs to anon;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.storage_deletion_jobs to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.storage_deletion_jobs to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.turn_feedback to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.turn_feedback to service_role;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.user_consents to authenticated;

grant DELETE, INSERT, MAINTAIN, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE on table public.user_consents to service_role;

-- Function execute revocations

revoke all on function public.handle_new_user() from public;

revoke all on function public.purge_expired_idempotency_records(p_batch_size integer) from public;

revoke all on function public.recalculate_turn_feedback_overall_score() from public;

revoke all on function public.set_architecture_record_updated_at() from public;

revoke all on function public.set_updated_at() from public;

revoke all on function public.synchronize_interview_question_count() from public;

revoke all on function public.validate_feedback_emotion_limit() from public;

revoke all on function public.validate_idempotency_job_owner() from public;

revoke all on function public.validate_idempotency_transition() from public;

revoke all on function public.validate_interview_answer_message() from public;

revoke all on function public.validate_practice_room_start() from public;

revoke all on function public.validate_processing_job_domain_state() from public;

revoke all on function public.validate_processing_job_owner_target() from public;

revoke all on function public.validate_processing_job_transition() from public;

revoke all on function public.validate_profile_onboarding_completion() from public;

-- Function grants

grant EXECUTE on function public.handle_new_user() to service_role;

grant EXECUTE on function public.purge_expired_idempotency_records(p_batch_size integer) to anon;

grant EXECUTE on function public.purge_expired_idempotency_records(p_batch_size integer) to authenticated;

grant EXECUTE on function public.purge_expired_idempotency_records(p_batch_size integer) to service_role;

grant EXECUTE on function public.recalculate_turn_feedback_overall_score() to anon;

grant EXECUTE on function public.recalculate_turn_feedback_overall_score() to authenticated;

grant EXECUTE on function public.recalculate_turn_feedback_overall_score() to public;

grant EXECUTE on function public.recalculate_turn_feedback_overall_score() to service_role;

grant EXECUTE on function public.set_architecture_record_updated_at() to anon;

grant EXECUTE on function public.set_architecture_record_updated_at() to authenticated;

grant EXECUTE on function public.set_architecture_record_updated_at() to public;

grant EXECUTE on function public.set_architecture_record_updated_at() to service_role;

grant EXECUTE on function public.set_updated_at() to anon;

grant EXECUTE on function public.set_updated_at() to authenticated;

grant EXECUTE on function public.set_updated_at() to public;

grant EXECUTE on function public.set_updated_at() to service_role;

grant EXECUTE on function public.synchronize_interview_question_count() to anon;

grant EXECUTE on function public.synchronize_interview_question_count() to authenticated;

grant EXECUTE on function public.synchronize_interview_question_count() to public;

grant EXECUTE on function public.synchronize_interview_question_count() to service_role;

grant EXECUTE on function public.validate_feedback_emotion_limit() to anon;

grant EXECUTE on function public.validate_feedback_emotion_limit() to authenticated;

grant EXECUTE on function public.validate_feedback_emotion_limit() to public;

grant EXECUTE on function public.validate_feedback_emotion_limit() to service_role;

grant EXECUTE on function public.validate_idempotency_job_owner() to anon;

grant EXECUTE on function public.validate_idempotency_job_owner() to authenticated;

grant EXECUTE on function public.validate_idempotency_job_owner() to service_role;

grant EXECUTE on function public.validate_idempotency_transition() to anon;

grant EXECUTE on function public.validate_idempotency_transition() to authenticated;

grant EXECUTE on function public.validate_idempotency_transition() to service_role;

grant EXECUTE on function public.validate_interview_answer_message() to anon;

grant EXECUTE on function public.validate_interview_answer_message() to authenticated;

grant EXECUTE on function public.validate_interview_answer_message() to public;

grant EXECUTE on function public.validate_interview_answer_message() to service_role;

grant EXECUTE on function public.validate_practice_room_start() to anon;

grant EXECUTE on function public.validate_practice_room_start() to authenticated;

grant EXECUTE on function public.validate_practice_room_start() to public;

grant EXECUTE on function public.validate_practice_room_start() to service_role;

grant EXECUTE on function public.validate_processing_job_domain_state() to anon;

grant EXECUTE on function public.validate_processing_job_domain_state() to authenticated;

grant EXECUTE on function public.validate_processing_job_domain_state() to service_role;

grant EXECUTE on function public.validate_processing_job_owner_target() to anon;

grant EXECUTE on function public.validate_processing_job_owner_target() to authenticated;

grant EXECUTE on function public.validate_processing_job_owner_target() to service_role;

grant EXECUTE on function public.validate_processing_job_transition() to anon;

grant EXECUTE on function public.validate_processing_job_transition() to authenticated;

grant EXECUTE on function public.validate_processing_job_transition() to service_role;

grant EXECUTE on function public.validate_profile_onboarding_completion() to anon;

grant EXECUTE on function public.validate_profile_onboarding_completion() to authenticated;

grant EXECUTE on function public.validate_profile_onboarding_completion() to public;

grant EXECUTE on function public.validate_profile_onboarding_completion() to service_role;

-- Required configuration data

insert into public.processing_timeout_policies (job_type, timeout_seconds, max_attempts, is_active) values
  ('conversation_text', 15, 3, 't'),
  ('emotion_analysis', 15, 3, 't'),
  ('interview_configuration_generation', 60, 3, 't'),
  ('interview_document_analysis', 60, 3, 't'),
  ('session_result_generation', 60, 3, 't'),
  ('tts_generation', 45, 3, 't'),
  ('turn_feedback', 30, 3, 't')
on conflict (job_type) do update set timeout_seconds=excluded.timeout_seconds, max_attempts=excluded.max_attempts, is_active=excluded.is_active, updated_at=now();

reset search_path;

