update public.processing_timeout_policies
set timeout_seconds = 45,
    updated_at = now()
where job_type = 'conversation_text';
