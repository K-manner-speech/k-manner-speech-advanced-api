-- personas.description은 이제 대화 프롬프트로 전달되어 페르소나의 말투를 결정한다.
-- 기존 두 페르소나의 설명은 "테스트 페르소나"라고만 적혀 있어 관계도 말투도 알려주지
-- 못했다. 이서준 선배와 같은 형식으로 관계·말투·성격을 담아 다시 쓴다.

update public.personas
set description = '개발팀을 이끄는 40대 팀장. 팀원에게 존댓말로 정중하되 분명하게 '
                  '업무를 요청하고, 일정과 근거를 중요하게 여긴다.'
where id = '10000000-0000-4000-8000-000000000001';

update public.personas
set description = '서비스 이용 중 불편을 겪은 30대 고객. 존댓말을 쓰지만 불만이 '
                  '드러나며, 구체적인 해결 방안을 듣고 싶어 한다.'
where id = '10000000-0000-4000-8000-000000000002';

-- 테스트 시드가 쓰던 9001/9002를 정리한다. 나중에 항목을 사이에 끼워 넣어도 전체를
-- 다시 번호 매기지 않도록 10 단위로 띄우고, 학습자가 쉬운 것부터 보도록 난이도 순으로
-- 배치한다.

update public.personas set sort_order = 10
where id = '10000000-0000-4000-8000-000000000003';   -- 이서준 선배
update public.personas set sort_order = 20
where id = '10000000-0000-4000-8000-000000000001';   -- 김민준 팀장
update public.personas set sort_order = 30
where id = '10000000-0000-4000-8000-000000000002';   -- 박서연 고객

update public.scenarios set sort_order = 10
where id = '20000000-0000-4000-8000-000000000003';   -- 학교 식당 위치 묻기 (easy)
update public.scenarios set sort_order = 20
where id = '20000000-0000-4000-8000-000000000001';   -- 업무 일정 조율 (medium)
update public.scenarios set sort_order = 30
where id = '20000000-0000-4000-8000-000000000002';   -- 고객 불만 응대 (hard)
