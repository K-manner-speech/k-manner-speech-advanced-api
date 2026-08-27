create table public.document_chunks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  document_id uuid not null references public.interview_documents(id) on delete cascade,
  analysis_id uuid not null references public.interview_document_analyses(id) on delete cascade,
  document_version integer not null check (document_version > 0),
  chunk_index integer not null check (chunk_index >= 0),
  section text not null,
  content text not null check (length(btrim(content)) > 0),
  token_count integer not null check (token_count > 0),
  source_ref jsonb not null default '{}'::jsonb,
  embedding extensions.vector(3072) not null,
  created_at timestamptz not null default now(),
  unique (document_id, document_version, chunk_index)
);

create index document_chunks_owner_version_idx
  on public.document_chunks (user_id, document_id, document_version);

create index document_chunks_embedding_cosine_idx
  on public.document_chunks using hnsw
  ((embedding::extensions.halfvec(3072)) extensions.halfvec_cosine_ops);

alter table public.document_chunks enable row level security;
revoke all on table public.document_chunks from anon, authenticated;
grant select, insert, update, delete on table public.document_chunks to service_role;

create table public.interview_evaluation_scores (
  id uuid primary key default gen_random_uuid(),
  result_id uuid not null references public.session_results(id) on delete cascade,
  category text not null check (
    category in (
      'question_understanding_fit',
      'answer_structure',
      'specificity_evidence',
      'job_fit_problem_solving',
      'delivery_attitude'
    )
  ),
  score smallint not null check (score between 1 and 20),
  strength_text text,
  suggestion_text text,
  evidence_text text,
  created_at timestamptz not null default now(),
  unique (result_id, category)
);

create index interview_evaluation_scores_result_idx
  on public.interview_evaluation_scores (result_id);

alter table public.interview_evaluation_scores enable row level security;
revoke all on table public.interview_evaluation_scores from anon, authenticated;
grant select, insert, update, delete on table public.interview_evaluation_scores to service_role;

alter table public.session_results
  add constraint session_results_interview_score_contract check (
    interview_setup_snapshot is null
    or (
      result_status = 'succeeded'
      and cardinality(missing_categories) = 0
      and overall_score between 5 and 100
    )
    or (
      result_status = 'partial'
      and cardinality(missing_categories) between 1 and 4
      and overall_score is null
    )
    or (
      result_status in ('processing', 'failed')
      and overall_score is null
    )
  ) not valid;
