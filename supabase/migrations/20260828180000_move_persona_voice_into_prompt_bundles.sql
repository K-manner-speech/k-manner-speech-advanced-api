-- 페르소나의 정체성·말투·음성을 YAML 프롬프트 번들 한 곳으로 모은다.
--
-- 지금까지는 두 곳이 같은 일을 했다. personas.description 이 대화 payload 로 나가
-- 말투를 정했고, app/ai/prompts/catalog 의 번들도 같은 목적을 위해 준비돼 있었다.
-- 번들을 쓰는 페르소나가 없어 충돌은 없었지만, 한쪽만 고치면 어긋나는 구조였다.
--
-- 이제 번들이 단일 출처다. voice_key/voice_style 도 번들의 voice 블록으로 옮겨,
-- "이 페르소나가 누구이고 어떻게 말하고 어떤 목소리인가"가 한 파일에 모인다.
--
-- description 컬럼은 남긴다. 프론트 페르소나 카드가 쓰는 표시용 텍스트이고,
-- 더 이상 프롬프트로는 나가지 않는다.

update public.personas set prompt_bundle_key = 'seojun'
where id = '10000000-0000-4000-8000-000000000003';   -- 이서준 선배

update public.personas set prompt_bundle_key = 'minjun'
where id = '10000000-0000-4000-8000-000000000001';   -- 김민준 팀장

update public.personas set prompt_bundle_key = 'seoyeon'
where id = '10000000-0000-4000-8000-000000000002';   -- 박서연 고객

alter table public.personas drop column voice_key;
alter table public.personas drop column voice_style;
