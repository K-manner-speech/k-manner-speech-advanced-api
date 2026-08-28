-- 페르소나별 TTS 음성 설정을 추가한다.
--   voice_key   : Gemini 사전 정의 음성 이름. NULL이면 worker 기본값('Kore')을 쓴다.
--   voice_style : 발화 지시문 앞에 붙는 화자 설정. NULL이면 감정 지시문만 나간다.
-- 두 값 모두 NULL이면 기존 동작과 완전히 동일하다.

alter table public.personas add column if not exists voice_key text;
alter table public.personas add column if not exists voice_style text;

comment on column public.personas.voice_key is
  'Gemini TTS 사전 정의 음성 이름(예: Kore, Achird). NULL이면 worker 기본값.';
comment on column public.personas.voice_style is
  '발화 지시문에 앞세울 화자 설정(예: 20대 초반 남자 대학생이 친한 후배에게 말하듯).';

-- 남성 캐릭터 두 명에 음성을 지정한다. 박서연 고객은 NULL로 두어 기본값을 유지한다.
update public.personas
set voice_key = 'Achird',
    voice_style = '20대 초반 남자 대학생이 친한 후배에게 편하게 말하듯'
where id = '10000000-0000-4000-8000-000000000003';

update public.personas
set voice_key = 'Iapetus',
    voice_style = '30대 후반 남성 팀장이 팀원에게 차분하고 정중하게 말하듯'
where id = '10000000-0000-4000-8000-000000000001';
