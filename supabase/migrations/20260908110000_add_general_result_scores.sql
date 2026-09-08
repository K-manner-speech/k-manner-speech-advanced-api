-- 결과 요약 화면이 종합 점수만이 아니라 항목별 점수를 보여 준다. 지금까지 네
-- 항목 점수는 턴별 피드백에만 있어, 연습 전체로는 어디가 부족한지 알 수 없었다.
-- 면접의 interview_evaluation_scores 와 같은 모양으로 둔다.
create table if not exists public.general_evaluation_scores (
  id uuid primary key default gen_random_uuid(),
  result_id uuid not null references public.session_results(id) on delete cascade,
  category text not null check (
    category in ('honorifics', 'courtesy', 'context_fit', 'naturalness')
  ),
  score integer not null check (score between 5 and 25),
  strength_text text,
  suggestion_text text,
  evidence_text text,
  created_at timestamptz not null default now(),
  unique (result_id, category)
);

create index if not exists general_evaluation_scores_result_idx
  on public.general_evaluation_scores (result_id);

alter table public.general_evaluation_scores enable row level security;

comment on table public.general_evaluation_scores is
  '자유채팅·시나리오 결과의 항목별 점수입니다. 결과 하나에 항목당 한 행입니다.';
