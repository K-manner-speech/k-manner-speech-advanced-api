begin;

insert into public.processing_timeout_policies (
  job_type,
  timeout_seconds,
  max_attempts,
  is_active,
  updated_at
)
values (
  'session_result_generation',
  60,
  3,
  true,
  now()
)
on conflict (job_type) do update set
  timeout_seconds = excluded.timeout_seconds,
  max_attempts = excluded.max_attempts,
  is_active = excluded.is_active,
  updated_at = now();

commit;
