-- scenario_goal_progress 의 job deadline 이 20초였는데, 판정에 쓰는 OpenAI
-- 클라이언트의 timeout 이 30초다. deadline 은 job 생성 시점부터 흐르므로 queue
-- 대기까지 더하면 성공한 응답이 이미 만료된 job 에 도착한다. 워커가 잠깐만
-- 멈춰도 즉시 JOB_DEADLINE_EXCEEDED 로 실패했다.

update public.processing_timeout_policies
set timeout_seconds = 60, updated_at = now()
where job_type = 'scenario_goal_progress';
