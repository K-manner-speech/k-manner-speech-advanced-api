create table if not exists public.tts_stream_chunks (
  message_audio_id uuid not null references public.message_audio(id) on delete cascade,
  processing_token uuid not null,
  sequence_no integer not null check (sequence_no >= 0),
  pcm bytea not null check (octet_length(pcm) > 0),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '5 minutes'),
  primary key (message_audio_id, processing_token, sequence_no)
);

create index if not exists tts_stream_chunks_expiry_idx
  on public.tts_stream_chunks (expires_at);

alter table public.tts_stream_chunks enable row level security;

comment on table public.tts_stream_chunks is
  'Worker가 생성 중인 TTS PCM을 인증된 API 스트림으로 중계하는 5분 수명의 임시 청크입니다.';
