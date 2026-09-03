-- processing_jobs 의 두 번째 검증 트리거도 job_type 을 CASE 로 열거하고 ELSE 가
-- 없다. 새 유형은 CASE_NOT_FOUND 로 실패하고, 설령 통과하더라도 succeeded 규칙에
-- 분기가 없어 v_valid 가 false 로 남아 다시 실패한다.
--
-- scenario_goal_progress 는 완료 시 room_goal_evaluations.evaluation_status 가
-- succeeded 가 된다.

create or replace function public.validate_processing_job_domain_state()
returns trigger
language plpgsql
security definer
set search_path to 'public', 'pg_temp'
as $function$
declare
  v_domain_status text;
  v_valid boolean := false;
begin
  if new.status = 'cancelled' then
    return null;
  end if;

  case new.job_type
    when 'conversation_text' then
      select processing_status into v_domain_status
      from public.message_ai_processing where id = new.message_ai_processing_id;
    when 'emotion_analysis' then
      select processing_status into v_domain_status
      from public.message_emotion_analysis where id = new.message_emotion_analysis_id;
    when 'tts_generation' then
      select generation_status into v_domain_status
      from public.message_audio where id = new.message_audio_id;
    when 'turn_feedback' then
      select analysis_status into v_domain_status
      from public.turn_feedback where id = new.turn_feedback_id;
    when 'scenario_goal_progress' then
      select evaluation_status into v_domain_status
      from public.room_goal_evaluations where id = new.room_goal_evaluation_id;
    when 'interview_document_analysis' then
      select processing_status into v_domain_status
      from public.interview_document_analyses where id = new.interview_document_analysis_id;
    when 'interview_configuration_generation' then
      select status into v_domain_status
      from public.interview_configurations where id = new.interview_configuration_id;
    when 'session_result_generation' then
      select result_status into v_domain_status
      from public.session_results where id = new.session_result_id;
    else
      raise exception using
        errcode = '23514',
        message = format('domain state validation is not defined for job type %L', new.job_type);
  end case;

  if new.status in ('queued', 'processing') then
    v_valid := v_domain_status = 'processing';
  elsif new.status = 'failed' then
    v_valid := v_domain_status = 'failed';
  elsif new.status = 'succeeded' and new.job_type in (
    'conversation_text', 'emotion_analysis', 'interview_document_analysis',
    'scenario_goal_progress'
  ) then
    v_valid := v_domain_status = 'succeeded';
  elsif new.status = 'succeeded' and new.job_type = 'tts_generation' then
    v_valid := v_domain_status = 'ready';
  elsif new.status = 'succeeded' and new.job_type = 'turn_feedback' then
    v_valid := v_domain_status in ('ready', 'partial');
  elsif new.status = 'succeeded' and new.job_type = 'interview_configuration_generation' then
    v_valid := v_domain_status = 'ready';
  elsif new.status = 'succeeded' and new.job_type = 'session_result_generation' then
    v_valid := v_domain_status in ('partial', 'succeeded');
  end if;

  if not coalesce(v_valid, false) then
    raise exception using errcode = '23514', message = 'processing job/domain status mismatch';
  end if;
  return null;
end $function$;
