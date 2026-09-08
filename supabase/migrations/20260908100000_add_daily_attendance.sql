-- 홈 화면의 출석과 연속 학습을 위한 기록이다. 하루 경계는 사용자가 체감하는
-- 날짜여야 하므로 Asia/Seoul 기준 날짜를 저장한다. profiles 에 시간대가 없어
-- 지금은 고정값을 쓰고, 시간대를 받게 되면 이 컬럼 계산만 바꾸면 된다.
-- 클라이언트가 보낸 날짜는 조작할 수 있으므로 서버가 정한다.
create table if not exists public.daily_attendances (
  user_id uuid not null references auth.users(id) on delete cascade,
  attended_on date not null,
  created_at timestamptz not null default now(),
  primary key (user_id, attended_on)
);

-- 연속 일수와 최근 7일 집계를 모두 사용자별 날짜 역순으로 훑는다.
create index if not exists daily_attendances_user_date_idx
  on public.daily_attendances (user_id, attended_on desc);

alter table public.daily_attendances enable row level security;

comment on table public.daily_attendances is
  '사용자가 출석하기를 누른 날짜입니다. 하루에 한 행이며 Asia/Seoul 기준입니다.';
