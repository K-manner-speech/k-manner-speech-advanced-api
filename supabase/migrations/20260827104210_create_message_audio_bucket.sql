-- The TTS worker uploads persona replies to the 'message-audio' bucket
-- (worker/domain_adapters.py TTSAdapter.complete), but the bucket was never
-- created, so every TTS generation failed with STORAGE_UNAVAILABLE.
-- Private like 'interview-documents': the API hands out short-lived signed URLs.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'message-audio',
  'message-audio',
  false,
  10485760,
  array['audio/wav']
)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
