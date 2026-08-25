create extension if not exists pgmq cascade;

select pgmq.create('conversation_text');
select pgmq.create('conversation_text_dlq');
select pgmq.create('interactive_ai');
select pgmq.create('interactive_ai_dlq');
select pgmq.create('document_analysis');
select pgmq.create('document_analysis_dlq');

create table public.worker_heartbeats (
  worker_id text not null,
  queue_name text not null,
  started_at timestamp with time zone default now() not null,
  last_seen_at timestamp with time zone default now() not null,
  primary key (worker_id, queue_name),
  constraint worker_heartbeats_queue_name_check check (
    queue_name in ('conversation_text', 'interactive_ai', 'document_analysis')
  )
);

create index worker_heartbeats_queue_freshness_idx
  on public.worker_heartbeats (queue_name, last_seen_at desc);

alter table public.worker_heartbeats enable row level security;

revoke all on table public.worker_heartbeats from public;
revoke all on table public.worker_heartbeats from anon, authenticated;
revoke all on schema pgmq from anon, authenticated;
revoke execute on all functions in schema pgmq from anon, authenticated;
