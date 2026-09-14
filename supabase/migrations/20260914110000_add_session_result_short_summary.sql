-- 피드백 목록에 보여 줄 짧은 요약을 따로 받는다.
--
-- summary 는 평균 187자, 길게는 300자라 목록 카드에서 대여섯 줄을 차지했다.
-- 잘라서 보여 주면 문장이 끊겨 무슨 말인지 알 수 없다. 목록은 훑는 화면이고
-- 상세는 읽는 화면이라 필요한 길이가 달라, 한 번의 AI 응답에서 두 문장을 함께
-- 받아 각 화면이 제 길이를 쓴다.
--
-- 이미 만들어진 결과는 이 값이 비어 있다. 화면은 그때 summary 를 두 줄까지만
-- 보여 주는 기존 방식으로 되돌아간다.

alter table public.session_results add column if not exists short_summary text;

alter table public.session_results
drop constraint if exists session_results_short_summary_length;

alter table public.session_results
add constraint session_results_short_summary_length
check (short_summary is null or char_length(short_summary) <= 60);

comment on column public.session_results.short_summary is
'피드백 목록 카드에 보여 줄 한 문장 요약입니다. 상세 화면은 summary 를 씁니다.';
