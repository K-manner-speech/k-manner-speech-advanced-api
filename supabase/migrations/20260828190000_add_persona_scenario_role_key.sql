-- (페르소나, 시나리오) 조합의 역할을 YAML 조각으로 옮긴다.
--
-- relationship_label 은 '상사', '담당자' 같은 명사 하나라 프롬프트로서 정보량이
-- 거의 없었다. 이제 DB 는 어떤 역할인지 가리키는 키만 갖고, 그 역할이 무엇을
-- 뜻하는지는 app/ai/prompts/catalog/roles 의 조각이 설명한다.
--
-- 역할은 페르소나 번들에 넣을 수 없다. 같은 김민준 팀장이 '업무 일정 조율'에서는
-- 상사이고 '고객 불만 응대'에서는 함께 대응하는 담당자다. 페르소나 하나당 파일
-- 하나인 번들로는 이 조합별 차이를 표현할 수 없어, 연결은 DB 에 남긴다.
--
-- relationship_label 은 그대로 둔다. 카탈로그 API 의 allowed_personas /
-- allowed_scenarios 가 노출하는 표시용 값이다.

alter table public.persona_scenarios add column role_key text;

alter table public.persona_scenarios
add constraint persona_scenarios_role_key_format
check (role_key is null or role_key ~ '^[a-z0-9_-]+$');

comment on column public.persona_scenarios.role_key is
'app/ai/prompts/catalog/roles 아래 YAML 조각의 확장자 없는 파일명';

update public.persona_scenarios set role_key = 'senior'
where persona_id = '10000000-0000-4000-8000-000000000003'
  and scenario_id = '20000000-0000-4000-8000-000000000003';

update public.persona_scenarios set role_key = 'supervisor'
where persona_id = '10000000-0000-4000-8000-000000000001'
  and scenario_id = '20000000-0000-4000-8000-000000000001';

update public.persona_scenarios set role_key = 'colleague'
where persona_id = '10000000-0000-4000-8000-000000000001'
  and scenario_id = '20000000-0000-4000-8000-000000000002';

update public.persona_scenarios set role_key = 'customer'
where persona_id = '10000000-0000-4000-8000-000000000002'
  and scenario_id = '20000000-0000-4000-8000-000000000002';
