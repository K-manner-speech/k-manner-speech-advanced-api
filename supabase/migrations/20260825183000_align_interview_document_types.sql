-- Keep the database contract aligned with the public interview API.
alter table public.interview_documents
  drop constraint if exists interview_documents_type_check;

alter table public.interview_documents
  add constraint interview_documents_type_check
  check (document_type = any (array['resume'::text, 'portfolio'::text,
                                    'self_introduction'::text]));
