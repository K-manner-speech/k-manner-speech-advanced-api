-- job 생성 시 deadline 은 app/services/jobs.py 의 _DEADLINES_SECONDS 가 정하고,
-- reaper 가 거둔 job 을 재시도할 때의 새 deadline 은 이 표의 timeout_seconds 가
-- 정한다. 두 값이 어긋나 있었다: 코드는 180초인데 표는 60초라, 면접 구성과
-- 종합 결과 job 이 재시도에서 예산의 3분의 1만 받았다. 두 job 모두 단일 AI
-- 호출로 끝나지 않아 60초로는 정상 응답 직전에 다시 만료된다.

update public.processing_timeout_policies
set timeout_seconds = 180, updated_at = now()
where job_type in ('interview_configuration_generation', 'session_result_generation');
