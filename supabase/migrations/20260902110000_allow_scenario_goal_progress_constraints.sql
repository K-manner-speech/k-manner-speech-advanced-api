-- 새 job 유형과 새 base queue 를 기존 CHECK 제약들이 막고 있었다.
-- 제약이 값 목록을 그대로 열거하는 방식이라, 코드에 유형을 추가해도 DB 가
-- 거부한다. worker 루프는 예외를 잡아 롤백·재시도만 반복하므로 조용히 실패한다.

-- 1) evaluation_ai worker 의 하트비트가 거부되어 readiness 가 계속
--    worker_heartbeat=false 를 반환했다.
alter table public.worker_heartbeats
  drop constraint if exists worker_heartbeats_queue_name_check;

alter table public.worker_heartbeats
  add constraint worker_heartbeats_queue_name_check
  check (
    queue_name = any (
      array['conversation_text', 'interactive_ai', 'evaluation_ai', 'document_analysis']
    )
  );

-- 2) scenario_goal_progress job 자체를 insert 할 수 없었다.
alter table public.processing_jobs
  drop constraint if exists processing_jobs_job_type_check;

alter table public.processing_jobs
  add constraint processing_jobs_job_type_check
  check (
    job_type = any (
      array[
        'conversation_text', 'emotion_analysis', 'tts_generation', 'turn_feedback',
        'interview_document_analysis', 'interview_configuration_generation',
        'session_result_generation', 'scenario_goal_progress'
      ]
    )
  );

-- 3) 대상 컬럼이 정확히 하나여야 하는데 room_goal_evaluation_id 가 빠져 있어
--    새 job 은 num_nonnulls 가 0 이 된다.
alter table public.processing_jobs
  drop constraint if exists processing_jobs_target_count_check;

alter table public.processing_jobs
  add constraint processing_jobs_target_count_check
  check (
    num_nonnulls(
      message_ai_processing_id, message_emotion_analysis_id, message_audio_id,
      turn_feedback_id, interview_document_analysis_id, interview_configuration_id,
      session_result_id, room_goal_evaluation_id
    ) = 1
  );

-- 4) job 유형과 대상 컬럼의 짝을 열거하는 제약.
alter table public.processing_jobs
  drop constraint if exists processing_jobs_type_target_check;

alter table public.processing_jobs
  add constraint processing_jobs_type_target_check
  check (
    (job_type = 'conversation_text' and message_ai_processing_id is not null)
    or (job_type = 'emotion_analysis' and message_emotion_analysis_id is not null)
    or (job_type = 'tts_generation' and message_audio_id is not null)
    or (job_type = 'turn_feedback' and turn_feedback_id is not null)
    or (job_type = 'interview_document_analysis' and interview_document_analysis_id is not null)
    or (
      job_type = 'interview_configuration_generation' and interview_configuration_id is not null
    )
    or (job_type = 'session_result_generation' and session_result_id is not null)
    or (job_type = 'scenario_goal_progress' and room_goal_evaluation_id is not null)
  );

-- 5) 진행 단계 열거. adapter 가 claim 할 때 provider_processing 을 쓴다.
alter table public.processing_jobs
  drop constraint if exists processing_jobs_progress_check;

alter table public.processing_jobs
  add constraint processing_jobs_progress_check
  check (
    (status <> 'processing' and progress_stage is null)
    or (
      status = 'processing'
      and (
        progress_stage is null
        or (
          job_type = 'conversation_text'
          and progress_stage = any (
            array['context_preparing', 'provider_processing', 'saving_response']
          )
        )
        or (
          job_type = 'emotion_analysis'
          and progress_stage = any (array['provider_processing', 'saving_analysis'])
        )
        or (
          job_type = 'tts_generation'
          and progress_stage = any (array['provider_processing', 'storing_audio'])
        )
        or (
          job_type = 'turn_feedback'
          and progress_stage = any (array['provider_processing', 'saving_feedback'])
        )
        or (
          job_type = 'interview_document_analysis'
          and progress_stage = any (
            array['extracting_text', 'chunking', 'embedding', 'saving_analysis']
          )
        )
        or (
          job_type = 'interview_configuration_generation'
          and progress_stage = any (
            array['retrieving_evidence', 'provider_processing', 'saving_configuration']
          )
        )
        or (
          job_type = 'session_result_generation'
          and progress_stage = any (
            array['aggregating_evidence', 'provider_processing', 'saving_result']
          )
        )
        or (
          job_type = 'scenario_goal_progress'
          and progress_stage = any (array['provider_processing', 'saving_progress'])
        )
      )
    )
  );
