-- interview_configurations.document_version_snapshot 은 conditions 만 담고 있었는데,
-- 그 값이 어디에서도 쓰이지 않아 코드에서 제거했다. 남은 값 중 두 건은 Swagger UI 가
-- dict[str, Any] 필드에 자동으로 채워 넣는 예시값(additionalProp1)이 그대로 저장된
-- 것이다. 읽지 않는 값이지만 남겨 두면 다음 사람이 계약으로 오해한다.
update public.interview_configurations
set document_version_snapshot = '{}'::jsonb, updated_at = now()
where document_version_snapshot is not null
  and document_version_snapshot <> '{}'::jsonb;

-- application_type 은 이제 '신입'·'경력'·'인턴' 만 받는다. 계약이 생기기 전 데이터에
-- 목록 밖의 값이 하나 남아 있다. 컬럼에 CHECK 를 걸지는 않지만 값은 맞춰 둔다.
update public.interview_setups
set application_type = null, updated_at = now()
where application_type is not null
  and application_type not in ('신입', '경력', '인턴');
