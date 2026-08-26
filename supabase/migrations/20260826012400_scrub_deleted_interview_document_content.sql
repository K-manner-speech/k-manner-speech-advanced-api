-- Preserve deletion audit metadata while removing extracted resume content.
update public.interview_documents
set extracted_content = '{}'::jsonb,
    updated_at = now()
where deleted_at is not null
  and extracted_content is distinct from '{}'::jsonb;
