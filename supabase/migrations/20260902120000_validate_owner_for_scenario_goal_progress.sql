-- processing_jobs 소유자 검증 트리거가 job_type 을 CASE 로 열거하는데 ELSE 가
-- 없어, 새 job 유형을 insert 하면 CASE_NOT_FOUND 로 실패했다. 제약과 달리
-- 함수 안에 숨어 있어 스키마만 봐서는 드러나지 않는다.
--
-- scenario_goal_progress 분기를 추가하고, 앞으로 유형을 빠뜨리면 조용히
-- 통과하지 않고 어떤 유형이 빠졌는지 말해주는 예외를 던지게 한다.

create or replace function public.validate_processing_job_owner_target()
returns trigger
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $function$
declare v_owner uuid;
begin
  case new.job_type
    when 'conversation_text' then
      select r.user_id into v_owner
      from public.message_ai_processing p
      join public.room_messages m on m.id = p.message_id
      join public.practice_rooms r on r.id = m.room_id
      where p.id = new.message_ai_processing_id;
    when 'emotion_analysis' then
      select r.user_id into v_owner
      from public.message_emotion_analysis e
      join public.room_messages m on m.id = e.message_id
      join public.practice_rooms r on r.id = m.room_id
      where e.id = new.message_emotion_analysis_id;
    when 'tts_generation' then
      select r.user_id into v_owner
      from public.message_audio a
      join public.room_messages m on m.id = a.message_id
      join public.practice_rooms r on r.id = m.room_id
      where a.id = new.message_audio_id;
    when 'turn_feedback' then
      select r.user_id into v_owner
      from public.turn_feedback f
      join public.room_messages m on m.id = f.message_id
      join public.practice_rooms r on r.id = m.room_id
      where f.id = new.turn_feedback_id;
    when 'scenario_goal_progress' then
      select r.user_id into v_owner
      from public.room_goal_evaluations g
      join public.practice_rooms r on r.id = g.room_id
      where g.id = new.room_goal_evaluation_id;
    when 'interview_document_analysis' then
      select a.user_id into v_owner
      from public.interview_document_analyses a
      where a.id = new.interview_document_analysis_id;
    when 'interview_configuration_generation' then
      select c.user_id into v_owner
      from public.interview_configurations c
      where c.id = new.interview_configuration_id;
    when 'session_result_generation' then
      select s.user_id into v_owner
      from public.session_results s
      where s.id = new.session_result_id;
    else
      raise exception using
        errcode = '23514',
        message = format('owner validation is not defined for job type %L', new.job_type);
  end case;

  if v_owner is null or v_owner <> new.user_id then
    raise exception using
      errcode = '23514',
      message = 'processing job owner does not match target owner';
  end if;
  return new;
end $function$;
