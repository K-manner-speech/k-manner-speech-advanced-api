-- 학교 선배에게 학교 식당 위치를 묻는 초급 시나리오를 시드한다.
-- 기존 카탈로그 시드와 같은 고정 UUID 규칙을 따른다:
--   personas 1000...  scenarios 2000...  scenario_success_conditions 3000...

insert into public.personas
  (id, name, role_title, description, avatar_key, is_active, sort_order)
values
  (
    '10000000-0000-4000-8000-000000000003',
    '이서준 선배',
    '학과 선배',
    '같은 학과 3학년 선배. 후배에게 편하게 반말로 말을 건네고, 캠퍼스 생활을 친절하게 알려 준다.',
    'campus-senior',
    true,
    1
  )
on conflict (id) do update set
  name = excluded.name,
  role_title = excluded.role_title,
  description = excluded.description,
  avatar_key = excluded.avatar_key,
  is_active = excluded.is_active,
  sort_order = excluded.sort_order;

insert into public.scenarios
  (id, practice_type, title, goal, location, difficulty,
   estimated_minutes, opening_message, max_turns, is_active, sort_order)
values
  (
    '20000000-0000-4000-8000-000000000003',
    'scenario',
    '학교 식당 위치 묻기',
    '선배에게 존댓말로 학교 식당 위치를 묻고, 안내를 받은 뒤 감사를 표현한다',
    '대학 캠퍼스',
    'easy',
    3,
    '어? 오랜만이네. 반갑다!',
    4,
    true,
    1
  )
on conflict (id) do update set
  practice_type = excluded.practice_type,
  title = excluded.title,
  goal = excluded.goal,
  location = excluded.location,
  difficulty = excluded.difficulty,
  estimated_minutes = excluded.estimated_minutes,
  opening_message = excluded.opening_message,
  max_turns = excluded.max_turns,
  is_active = excluded.is_active,
  sort_order = excluded.sort_order;

insert into public.persona_scenarios
  (persona_id, scenario_id, relationship_label)
values
  (
    '10000000-0000-4000-8000-000000000003',
    '20000000-0000-4000-8000-000000000003',
    '선배'
  )
on conflict (persona_id, scenario_id) do update set
  relationship_label = excluded.relationship_label;

insert into public.scenario_success_conditions
  (id, scenario_id, condition_key, description, is_required, sort_order)
values
  (
    '30000000-0000-4000-8000-000000000005',
    '20000000-0000-4000-8000-000000000003',
    'polite_greeting',
    '선배에게 존댓말로 인사한다',
    true,
    1
  ),
  (
    '30000000-0000-4000-8000-000000000006',
    '20000000-0000-4000-8000-000000000003',
    'clear_question',
    '학교 식당 위치를 구체적으로 묻는다',
    true,
    2
  ),
  (
    '30000000-0000-4000-8000-000000000007',
    '20000000-0000-4000-8000-000000000003',
    'gratitude',
    '안내를 받은 뒤 감사 인사를 한다',
    true,
    3
  )
on conflict (scenario_id, condition_key) do update set
  description = excluded.description,
  is_required = excluded.is_required,
  sort_order = excluded.sort_order;
