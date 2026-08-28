# scenarios/ — 문서용 폴더 (런타임 미연결)

이 폴더의 YAML은 **문서·기획 참고용**이다. `identities/`, `personalities/`, `modes/`,
`rules/`, `styles/`, `tasks/`는 `PromptComposer`가 실제로 읽어 프롬프트에 합성하지만,
이 폴더는 어떤 코드에서도 로드하지 않는다.

## 왜 DB가 아니라 여기에도 적어두나

`app/models/catalog.py`의 `Scenario`/`Persona`가 카탈로그의 SSOT다. 시나리오 값은
전부 Alembic 마이그레이션 시드로 들어가고, 런타임에는
`app/prompt_builder/general_chat.py`의 `_format_scenario()`가 DB row를 읽어 그 자리에서
프롬프트 텍스트로 조립한다. 즉 "시나리오 프롬프트"가 파일로 존재하지 않고 DB row로만
있어서, 새 시나리오를 구상하거나 기존 것을 리뷰할 때 마이그레이션 파일을 열어야 했다.

이 폴더는 그 값을 사람이 보기 편한 곳에 미러링해 둔 것뿐이다. **값을 바꾸고 싶으면
여기를 고치지 말고 새 Alembic 마이그레이션을 작성하라.** 이 폴더는 그 마이그레이션이
머지된 뒤에 맞춰 갱신한다(같은 PR에서 함께 갱신하는 것을 권장).

## 필드 대응표

| YAML 필드 | DB 컬럼 (`scenarios` 테이블) | 비고 |
|---|---|---|
| `id` | `id` | 자연키, `chat_rooms.scenario_id`가 참조 |
| `title_ko` | `title_ko` | 목록/상세 API에 노출 |
| `description` | `description` | 상황 설명 |
| `time_context` | `time_context` | 선택값 |
| `place_context` | `place_context` | 선택값 |
| `communication_goal` | `communication_goal` | 필수, 목표 달성 판정 기준 |
| `end_condition` | `end_condition` | 필수, 종료 조건 |
| `max_turns` | `max_turns` | 턴 상한 |
| `turn_limit_exit_line` | `turn_limit_exit_line` | 상한 도달 시 마무리 대사, 없으면 생략 |
| `opening_line` | `opening_line` | 입장 시 persona가 먼저 건네는 말, 없으면 생략 |
| `personas` | `persona_scenarios` 매핑 | 이 시나리오를 고를 수 있는 상대 id 목록 |

`_format_scenario()`가 실제로 프롬프트에 펼치는 필드는 `id`, `description`,
`time_context`, `place_context`, `communication_goal`, `end_condition`, `max_turns`,
`turn_limit_exit_line`뿐이다(`opening_line`은 방 생성 시 첫 메시지로만 쓰이고 매 턴
프롬프트에는 들어가지 않는다).

## 목록

| 파일 | 근거 마이그레이션 |
|---|---|
| [`interview.yaml`](interview.yaml) | `9c1f4b0a7d52_kan_16_catalog_tables_and_missing_models.py` |
| [`roleplay.yaml`](roleplay.yaml) | `9c1f4b0a7d52_kan_16_catalog_tables_and_missing_models.py` |
| [`campus_directions.yaml`](campus_directions.yaml) (길 물어보기) | `d5b8c07f9a13_campus_directions_scenario.py` + `e2f6a9c14d80_scenario_opening_line.py` |
