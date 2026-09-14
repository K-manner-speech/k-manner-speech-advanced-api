-- 한 시나리오에 상대가 둘 이상일 때 누구를 먼저 권할지 정한다.
--
-- '고객 불만 응대'에는 박서연 고객과 김민준 팀장(담당자)이 함께 등록돼 있다.
-- 그런데 이 시나리오에서 사용자는 상담원이고 첫 대사도 "서비스 이용 중 불편한
-- 점이 있었습니다"라 상대는 고객이어야 한다. 지금은 정렬 기준이 personas.sort_order
-- 뿐이라 김민준이 먼저 나와 화면이 엉뚱한 상대를 띄웠다.
--
-- 조합을 지우지 않고 순서만 둔다. 이미 김민준으로 진행 중인 방이 있어 조합을
-- 지우면 그 방의 프롬프트에서 관계가 사라진다.

alter table public.persona_scenarios add column if not exists sort_order integer;

comment on column public.persona_scenarios.sort_order is
'이 시나리오에서 상대를 권하는 순서. 작을수록 먼저이며 비어 있으면 personas.sort_order 를 따른다.';

update public.persona_scenarios set sort_order = 10
where scenario_id = '20000000-0000-4000-8000-000000000002'
  and persona_id = '10000000-0000-4000-8000-000000000002';  -- 박서연 고객

update public.persona_scenarios set sort_order = 20
where scenario_id = '20000000-0000-4000-8000-000000000002'
  and persona_id = '10000000-0000-4000-8000-000000000001';  -- 김민준 팀장(담당자)
