alter table public.interview_evaluation_scores
  add column if not exists improvement_summary text;

alter table public.interview_evaluation_scores
  drop constraint if exists interview_evaluation_scores_improvement_summary_length,
  add constraint interview_evaluation_scores_improvement_summary_length
  check (improvement_summary is null or char_length(improvement_summary) <= 45);
