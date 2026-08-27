# K-Manner Speech API 명세서

> 상태: 구현 전 확정 계약  
> 기준: `docs/PRD.md`, `docs/화면기획서.md`, `docs/ERD.md`, `docs/아키텍처.md` 및 2026-08-25까지 확정된 아키텍처 결정  
> 범위: HTTP 계약과 계층 책임. 기능 코드, SQL, RLS 구현, Provider prompt 및 DB migration은 포함하지 않는다.

## 1. 계약 원칙

- Base path는 `/api/v1`이다. OpenAPI artifact가 FastAPI와 React generated client의 단일 계약 원본이다.
- JSON은 `application/json; charset=utf-8`, 파일은 `multipart/form-data`를 사용한다.
- 날짜·시간은 UTC ISO 8601, ID와 `Idempotency-Key`는 UUID다.
- Browser는 Supabase Auth에서 얻은 access token을 `Authorization: Bearer <token>`으로 전달한다. 비밀번호는 FastAPI로 보내지 않는다.
- 판정은 서버가 한다. Client가 보낸 owner, 상태, 완료 여부, 질문 연결, Storage key는 신뢰하지 않는다.
- 다른 사용자 소유와 미존재 resource는 모두 `404`로 응답한다.
- 비동기 action은 `202 Accepted + JobRef`를 반환한다. React는 2초 간격으로 공통 Job endpoint를 polling하고 terminal 상태 또는 제품 최대 대기시간에 중단한다.
- 성공한 Job의 실제 결과는 `result_resource`가 가리키는 owner-checked domain endpoint에서 별도로 조회한다.

## 2. 인증과 접근 제어

### 2.1 인증

| 구분 | 계약 |
| --- | --- |
| 일반 API·Job polling | local JWT 검증, JWKS cache, `alg/iss/aud/exp/session_id` 검사 후 `(session_id,user_id)`가 `auth.sessions`에 존재하는지 확인 |
| `kid` miss·key rotation | JWKS refresh 후 정확히 1회 재검증 |
| 회원 탈퇴 등 민감 action | local 검증 후 Supabase Auth `get_user` 재확인 |
| 회원가입·로그인·복구·재설정·비밀번호 변경 | React → Supabase Auth 직접 호출; 본 명세의 FastAPI endpoint가 아님 |
| 세션 저장 | Browser `sessionStorage`; logout/account deletion 시 허용된 client state와 함께 삭제 |

### 2.2 Owner matrix

| Resource/action | Repository predicate 또는 owner chain | 추가 Service 판정 |
| --- | --- | --- |
| Profile·consent | `profiles.id/user_consents.user_id = jwt.sub` | onboarding 필수값·활성 필수 약관 version |
| Room | `practice_rooms.user_id = jwt.sub` | catalog 조합, 활성 room unique, 상태·turn limit |
| Message·AI·emotion·audio·feedback | child → `room_messages.room_id` → `practice_rooms.user_id = jwt.sub` | sender, retry 가능 상태, current audio |
| Result | `session_results.user_id = jwt.sub` | room과 독립 snapshot; 채용 pass/fail 생성 금지 |
| Interview document·analysis | direct `user_id = jwt.sub`, analysis는 document/version도 join | current version, MIME/parser/text threshold |
| Configuration·question | `interview_configurations.user_id = jwt.sub`; question → configuration | analysis snapshot, ready/current/final questions |
| Interview answer | question → configuration 및 message → room → owner | 현재 질문, user message, same room/configuration |
| Job | `processing_jobs.user_id = jwt.sub`와 target owner chain | result resource owner 재검증 |
| Storage | DB metadata owner/version + server object prefix | private bucket, short signed URL, service role server only |
| Idempotency | `(user_id, action_scope, key)` | fingerprint, lease/CAS, stored safe response |

Router나 Service의 owner-scoped 직접 SQL은 금지한다. Repository method는 `authenticated_user_id`를 필수 인자로 받고 read/update/delete predicate 안에 owner 조건을 포함한다.

## 3. 공통 HTTP 계약

### 3.1 오류 envelope

```json
{
  "code": "STABLE_ERROR_CODE",
  "message": "개발 및 fallback용 안전한 기본 문구",
  "fields": {},
  "field_errors": [{"field": "profile.birth_date", "code": "INVALID_DATE"}],
  "request_id": "uuid",
  "retryable": false
}
```

`fields`는 오류 전체에 적용되는 allowlist 기반 안전한 보조값이며 없으면 빈 object다. `field_errors`는 없으면 빈 배열이다. Client는 `code`를 i18n key로 바꾼다. token, signed URL, 내부 SQL/stack, Provider raw error, prompt/response는 포함하지 않는다.

| Status | 의미 |
| --- | --- |
| 200/201/204 | 조회·생성·본문 없는 성공 |
| 202 | 비동기 접수 |
| 400 | 문법·형식 외의 잘못된 요청 |
| 401 | Bearer 없음/만료/검증 실패 |
| 404 | 미존재 또는 비소유 |
| 409 | 상태 충돌, 멱등 충돌, lifecycle 충돌 |
| 413/415 | 파일 크기 초과/지원하지 않는 media |
| 422 | Pydantic 또는 domain validation 실패 |
| 429 | user backpressure 초과; retryable |
| 500 | 안전하게 일반화한 내부 오류 |
| 503 | DB/queue/readiness 또는 일시적 의존성 불가 |

### 3.2 멱등성

- 아래 표에서 `Idem=필수`인 요청은 `Idempotency-Key: UUID`가 필수다.
- `action_scope`는 표의 `operationId`와 1:1이다. Unique scope는 `(jwt.sub, operationId, key)`다.
- Server fingerprint는 의미 있는 path/query/body의 canonical JSON SHA-256이다. Multipart는 streaming file SHA-256과 안전한 metadata를 사용한다.
- 같은 key·같은 payload의 completed record는 생성 당시 `response_schema_version`의 안전 snapshot 또는 동일 Job을 재생한다.
- 같은 key·다른 payload는 `409 IDEMPOTENCY_KEY_REUSED`다.
- 같은 요청이 아직 claim 중이면 `409 IDEMPOTENCY_REQUEST_IN_PROGRESS`, `retryable=true`다. 계산 가능한 경우에만 `Retry-After`를 보낸다.
- Auth와 기본 DTO 검증은 claim 전에 수행한다. 확정적인 non-retryable 4xx만 terminal snapshot으로 저장한다. 429/5xx/timeout/부분 성공 가능성은 같은 key로 reconcile-first 복구한다.
- Snapshot에 raw 문서·대화, token, signed URL, Provider 원본은 저장하지 않는다.
- `account.delete`는 즉시 영구 삭제의 예외다. 처리 중·실패 재시도에는 `Idempotency-Key`를 사용하지만 성공한 Auth hard delete가 사용자와 `idempotency_records`를 함께 cascade 삭제하므로 completed snapshot을 보존하지 않는다. 성공 뒤 남은 token의 재호출은 session 검증에서 `401`이다.

### 3.3 Cursor pagination

Query는 `limit`, 선택적 opaque `cursor`를 받는다. 응답은 아래 구조다. Cursor는 owner-filtered 집합 안의 안정된 `(created_at,id)` 또는 resource별 문서화된 정렬키를 인코딩한다.

```json
{"items": [], "next_cursor": "opaque-or-null"}
```

`limit`의 수치는 구현 설정으로 검증하며 이 문서에서 임의 default/max를 정하지 않는다.

### 3.4 비동기 Job

```json
{
  "job_id": "uuid",
  "type": "conversation_text",
  "status": "queued"
}
```

Job status는 `queued|processing|succeeded|failed|cancelled`다. `progress.stage`는 실제 단계만 반환하며 퍼센트를 추정하지 않는다. Terminal job은 불변이다. API/user retry·regeneration은 새 `job_id`를 만들고, transport retry와 schema repair는 같은 Job 내부 counter다.

## 4. Endpoint 명세

모든 endpoint의 response body는 명시한 schema를 사용한다. `ErrorEnvelope`는 모든 오류에 공통이다.

### 4.1 Health

| operationId | Method/path | Auth | Idem | Request | Success | Errors | Owner/Service |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `health.live` | `GET /api/v1/health/live` | 없음 | - | 없음 | `200 HealthLive` | 500 | process 생존만; 사용자 데이터 없음 |
| `health.ready` | `GET /api/v1/health/ready` | 없음 | - | 없음 | `200 HealthReady` | 503 | DB, pgmq queues/extensions, 필수 timeout policy 7종, config, 필수 queue별 TTL 이내 worker heartbeat를 검증한다. Provider live call은 금지한다. |

### 4.2 Profile·onboarding·account

| operationId | Method/path | Auth | Idem | Request | Success | Errors | Owner/Service |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `me.get` | `GET /api/v1/me` | Bearer | - | 없음 | `200 MeResponse` | 401,404 | `profile.id=jwt.sub` |
| `me_profile.replace` | `PUT /api/v1/me/profile` | Bearer | - | `ProfileReplaceRequest` | `200 MeResponse` | 401,404,422 | body owner/completion 금지; missing requirements 계산 |
| `me_language.replace` | `PUT /api/v1/me/language` | Bearer | - | `LanguageReplaceRequest` | `200 OnboardingMutationResponse` | 401,404,422 | `ko|en`; Zustand/localStorage 값은 server 판정을 대체하지 않음 |
| `me_terms.replace` | `PUT /api/v1/me/terms` | Bearer | - | `TermsReplaceRequest` | `200 OnboardingMutationResponse` | 401,404,409,422 | 활성 필수 policy version과 일치 검증 |
| `onboarding.complete` | `POST /api/v1/me/onboarding/complete` | Bearer | 필수 | 빈 object | `200 MeResponse` | 401,404,409,422 | profile/language/필수 consent를 server가 재검증 후 완료 설정 |
| `account.delete` | `DELETE /api/v1/me` | Bearer+active `session_id`+`get_user` | 필수 | 없음 | `204` | 401,409,500,503 | claim 확정 후 일반 API 차단, Job cancel·user queue cleanup, `storage.objects` user prefix inventory의 실제 Storage API 삭제·잔존 0 확인, Auth hard delete/cascade 순서. 부분 삭제를 성공 처리하지 않으며 성공 멱등 snapshot은 보존하지 않음 |

Client는 `onboarding_completed`를 어떤 request에도 보낼 수 없다. Local MVP email verification은 비활성이다.

모든 인증 API는 JWT의 `session_id`가 `auth.sessions`에서 같은 `jwt.sub`에 속하는지 확인한다. 탈퇴 처리 중에는 일반 API를 `401 INVALID_AUTH_SESSION`으로 차단하되 `DELETE /api/v1/me`의 동일 작업 재시도만 세션 존재 검사를 통과할 수 있다. 세션 저장소를 확인할 수 없으면 `503 AUTH_SESSION_UNAVAILABLE`이며 local JWT 성공만으로 요청을 계속하지 않는다.

#### 로컬 MVP 테스트 약관 정책

| `consent_type` | `policy_version` | 동의 조건 | 상태 |
| --- | --- | --- | --- |
| `terms` | `v1` | 필수 | 활성 |
| `privacy` | `v1` | 필수 | 활성 |

`GET /api/v1/me`는 위 두 정책의 현재 동의 상태를 반환한다. `PUT /api/v1/me/terms`는 요청된
정책의 정확한 type/version과 `accepted:true`를 받아 저장하며, 두 필수 정책 모두 동의하지 않으면
`POST /api/v1/me/onboarding/complete`는 `409 ONBOARDING_REQUIREMENTS_MISSING`을 반환한다.
이 식별자는 로컬 MVP 테스트 계약이다. 실제 약관 본문이 변경되면 기존 동의 이력을 덮어쓰지
않고 새 `policy_version`을 발행하고 이전 version을 비활성화한다.

### 4.3 Catalog

| operationId | Method/path | Auth | Idem | Request | Success | Errors | Owner/Service |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `persona.list` | `GET /api/v1/personas` | Bearer | - | cursor,limit,filter | `200 Page[PersonaSummary]` | 401 | owner 없음; active catalog만 |
| `persona.get` | `GET /api/v1/personas/{persona_id}` | Bearer | - | path | `200 PersonaDetail` | 401,404 | owner 없음; 허용 scenario 포함 |
| `scenario.list` | `GET /api/v1/scenarios` | Bearer | - | cursor,limit,persona_id | `200 Page[ScenarioSummary]` | 401,404 | owner 없음; persona 허용 조합만 |
| `scenario.get` | `GET /api/v1/scenarios/{scenario_id}` | Bearer | - | path | `200 ScenarioDetail` | 401,404 | owner 없음; max turns와 성공 조건 제공 |

### 4.4 Rooms·messages

| operationId | Method/path | Auth | Idem | Request | Success | Errors | Owner/Service |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `room.create` | `POST /api/v1/rooms` | Bearer | 필수 | `RoomCreateRequest` | `201 Room`; 동일 활성 조합 재사용은 `200 Room` | 401,409,422 | jwt owner; persona/scenario 허용 조합과 active unique 판정. 일반/상황 연습 전용 |
| `room.list` | `GET /api/v1/rooms` | Bearer | - | cursor,limit,status,practice_type | `200 Page[RoomSummary]` | 401,422 | owner 집합 안 cursor |
| `room.get` | `GET /api/v1/rooms/{room_id}` | Bearer | - | path | `200 RoomDetail` | 401,404 | room owner |
| `room.delete` | `DELETE /api/v1/rooms/{room_id}` | Bearer | 필수 | 없음 | `204` | 401,404,409,503 | queue cancel/stale guard 후 종속 message/context/audio/feedback 삭제; 독립 result 유지 |
| `room_message.list` | `GET /api/v1/rooms/{room_id}/messages` | Bearer | - | cursor,limit | `200 Page[Message]` | 401,404,422 | room owner; sequence 안정 정렬 |
| `room_message.create` | `POST /api/v1/rooms/{room_id}/messages` | Bearer | 필수 | `MessageCreateRequest` | `202 MessageAccepted` | 401,404,409,422,429,503 | active/turn/현재 interview question 판정; user message+conversation job 원자 확정 |
| `message_response.retry` | `POST /api/v1/messages/{message_id}/retry-response` | Bearer | 필수 | 빈 object | `202 MessageAccepted` | 401,404,409,429,503 | 기존 실패 response processing target에 새 Job; 새 user message 금지 |

면접 답변은 별도 endpoint가 아니라 `room_message.create`를 사용하고 `current_interview_question_id`를 보낸다. Service가 `interview_answers`를 동일 transaction에서 연결한다.

### 4.5 Feedback·emotion·audio·repeat

| operationId | Method/path | Auth | Idem | Request | Success | Errors | Owner/Service |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `message_feedback.get` | `GET /api/v1/messages/{message_id}/feedback` | Bearer | - | path | `200 FeedbackResponse` | 401,404 | message→room owner; partial 허용 |
| `message_feedback.retry` | `POST /api/v1/messages/{message_id}/feedback/retry` | Bearer | 필수 | 빈 object | `202 DomainJobAccepted` | 401,404,409,429,503 | 같은 feedback row, 새 Job |
| `message_emotion.retry` | `POST /api/v1/messages/{message_id}/emotion/retry` | Bearer | 필수 | 빈 object | `202 DomainJobAccepted` | 401,404,409,429,503 | message→room owner와 retryable `failed` 상태를 검증하고 같은 emotion analysis row에 새 Job을 연결한다. |
| `message_tts.retry` | `POST /api/v1/messages/{message_id}/tts/retry` | Bearer | 필수 | 빈 object | `202 DomainJobAccepted` | 401,404,409,429,503 | 같은 audio logical target, 성공 연결 후 구 object 삭제 |
| `message_audio.get` | `GET /api/v1/messages/{message_id}/audio` | Bearer | - | path | `200 AudioAccessResponse` | 401,404,409 | current metadata·object prefix 재검증 후 short signed URL; URL 저장/log 금지 |
| `message_repeat.create` | `POST /api/v1/messages/{message_id}/repeat` | Bearer | 필수 | `RepeatRequest` | `202 MessageAccepted` | 401,404,409,422,429,503 | 추천 표현/허용 상태 판정 후 새 연습 message와 Job |

감정 결과는 `Message.emotion` 또는 `FeedbackResponse.emotions`로 조회하며 결과값을 직접 수정하는 API는 없다. 감정 분석 재시도는 `message_emotion.retry`만 사용한다. Service는 기존 `message_emotion_analysis` 행을 `processing`으로 전이하고 새 Job과 새 `processing_token`을 연결한다. 이전 처리 토큰의 늦은 결과는 현재 토큰과 일치하지 않으면 저장하지 않는다. `processing|succeeded` 상태, retry 불가능한 오류 또는 기존 유효 Job이 있으면 `409`다.

### 4.6 Jobs·results

| operationId | Method/path | Auth | Idem | Request | Success | Errors | Owner/Service |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `job.get` | `GET /api/v1/jobs/{job_id}` | Bearer | - | path | `200 Job` | 401,404 | direct job owner + target/result owner 재검증 |
| `room_result.get` | `GET /api/v1/rooms/{room_id}/result` | Bearer | - | path | `200 SessionResult` | 401,404,409 | room owner; result 없거나 processing 상태 구분 |
| `room_result.retry` | `POST /api/v1/rooms/{room_id}/result/retry` | Bearer | 필수 | 빈 object | `202 DomainJobAccepted` | 401,404,409,429,503 | 같은 failed result row에 새 Job을 만들고 60초 deadline·최대 3회 시도 정책을 적용한다. |
| `result.list` | `GET /api/v1/results` | Bearer | - | cursor,limit | `200 Page[SessionResultSummary]` | 401,422 | `result.user_id=jwt.sub` |
| `result.get` | `GET /api/v1/results/{result_id}` | Bearer | - | path | `200 SessionResult` | 401,404 | result direct owner |
| `result.delete` | `DELETE /api/v1/results/{result_id}` | Bearer | 필수 | 없음 | `204` | 401,404,409,503 | result/job lifecycle; room에는 영향 없음 |

Room이 `completed|failed`로 종료될 때 Service가 단일 `session_result` processing record를 만들고 결과 Job을 자동 enqueue한다. Client create endpoint는 없다. `session_result_generation`은 60초 deadline과 최대 3회 시도 정책을 사용한다.

### 4.7 Interview setup·documents·analysis

| operationId | Method/path | Auth | Idem | Request | Success | Errors | Owner/Service |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `interview_setup.create` | `POST /api/v1/interview-setups` | Bearer | 필수 | `InterviewSetupCreateRequest` | `201 InterviewSetup`; 동일 key·동일 payload 재요청도 생성 당시 `201` snapshot 재생 | 401,409,422,503 | `jwt.sub -> new setup.user_id`; owner/status/progress 입력 금지; 면접 문서·구성·연습방을 묶는 준비 단위 생성 |
| `interview_document.create` | `POST /api/v1/interview-documents` | Bearer | 필수 | `multipart DocumentUploadRequest` | `201 InterviewDocument` | 401,413,415,422,503 | max 10MB; 이력서·자기소개서는 PDF/DOCX, 포트폴리오는 PDF; magic/parser validation, server key/private bucket |
| `interview_document.list` | `GET /api/v1/interview-documents` | Bearer | - | cursor,limit,document_type | `200 Page[InterviewDocument]` | 401,422 | owner/current/version scope |
| `interview_document.get` | `GET /api/v1/interview-documents/{document_id}` | Bearer | - | path | `200 InterviewDocument` | 401,404 | direct owner |
| `interview_document.analyze` | `POST /api/v1/interview-documents/{document_id}/analyze` | Bearer | 필수 | 빈 object | `202 AnalysisAccepted` | 401,404,409,422,429,503 | current/version/text threshold; parse fail은 queue 금지 |
| `interview_document.replace` | `POST /api/v1/interview-documents/{document_id}/replace` | Bearer | 필수 | `multipart DocumentUploadRequest` | `201 InterviewDocument` | 401,404,409,413,415,422,503 | 새 version 확정, old job cancel, 이전 문서 논리 삭제, Storage 원본·해당 vector 정리, 완료된 분석 보존 |
| `interview_document.delete` | `DELETE /api/v1/interview-documents/{document_id}` | Bearer | 필수 | 없음 | `204` | 401,404,409,503 | 문서 row를 `is_current=false`, `deleted_at=now()`로 논리 삭제하고 Storage 원본과 해당 vector를 삭제하되 완료된 분석은 보존한다. 진행 중 Job은 cancel하고 미시작 configuration은 `invalidated`로 전이한다. |
| `interview_analysis.get` | `GET /api/v1/interview-analyses/{analysis_id}` | Bearer | - | path | `200 InterviewAnalysis` | 401,404 | analysis user + document owner/version |

OCR은 MVP에 없다. 스캔 PDF 또는 text threshold 미달은 `422 DOCUMENT_TEXT_NOT_EXTRACTABLE`이며 분석 Job을 만들지 않는다. 문서 원문은 응답하지 않는다.

삭제된 원본을 참조하는 보존된 분석은 과거 결과 조회에만 사용하고 새 분석 또는 면접 구성의 입력으로 사용하지 않는다. 해당 원본으로 아직 시작하지 않은 configuration은 `invalidated`다. 삭제된 원본의 `Storage path` 또는 `signed URL`은 어떤 분석·문서 응답에도 제공하지 않는다. 회원 탈퇴는 예외로 사용자 소유 문서 row, 완료된 분석, vector와 Storage object를 모두 영구 삭제한다.

### 4.8 Interview configuration·questions·practice

| operationId | Method/path | Auth | Idem | Request | Success | Errors | Owner/Service |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `interview_configuration.generate` | `POST /api/v1/interview-configurations` | Bearer | 필수 | `InterviewConfigurationGenerateRequest` | `202 ConfigurationAccepted` | 401,404,409,422,429,503 | analysis/document/version owner와 eligibility; processing configuration+Job 원자 생성 |
| `interview_configuration.get` | `GET /api/v1/interview-configurations/{configuration_id}` | Bearer | - | path | `200 InterviewConfiguration` | 401,404 | direct owner |
| `interview_question.list` | `GET /api/v1/interview-configurations/{configuration_id}/questions` | Bearer | - | path | `200 InterviewQuestionList` | 401,404,409 | owner; ready 이후 final ordered questions |
| `interview_configuration.regenerate` | `POST /api/v1/interview-configurations/{configuration_id}/regenerate` | Bearer | 필수 | `InterviewConfigurationRegenerateRequest` | `202 ConfigurationAccepted` | 401,404,409,422,429,503 | same type/target의 새 execution Job; current/상태 판정 |
| `interview_practice_room.create` | `POST /api/v1/interview-configurations/{configuration_id}/practice-room` | Bearer | 필수 | 빈 object | `201 Room` | 401,404,409,422,503 | owner+ready+current+final questions 검증; configuration `in_progress` 전환+room 원자 생성 |

Configuration generation은 `public.document_chunks`의 3072차원 pgvector에서 owner/document/analysis/version metadata prefilter 후 최대 8개 chunk와 설정된 threshold를 적용한다. 현행 Job deadline은 180초다. 통과 chunk가 없으면 fabrication 없이 `INTERVIEW_RAG_EVIDENCE_NOT_FOUND`로 실패한다. 질문은 configuration당 1~10개이고 source refs를 보존한다.

## 5. DTO schema

### 5.1 공통

| Schema | Fields |
| --- | --- |
| `ErrorEnvelope` | `code:string`, `message:string`, `fields:object`, `field_errors:FieldError[]`, `request_id:uuid`, `retryable:boolean` |
| `FieldError` | `field:string`, `code:string` |
| `Page[T]` | `items:T[]`, `next_cursor:string|null` |
| `JobRef` | `job_id:uuid`, `type:JobType`, `status:'queued'` |
| `DomainRef` | `type:string`, `id:uuid` |
| `JobProgress` | `stage:string|null`, `completed_units:integer|null`, `total_units:integer|null` |
| `JobError` | `code:string`, `retryable:boolean`, `meta:object|null` |
| `Job` | `id`, `type`, `status`, `progress`, `error|null`, `result_resource:DomainRef|null`, `created_at`, `updated_at` |

`JobType`은 `conversation_text|emotion_analysis|tts_generation|turn_feedback|interview_document_analysis|interview_configuration_generation|session_result_generation`이다. queued/terminal에서 progress stage는 null이다.

### 5.2 Onboarding·catalog

| Schema | Fields/constraints |
| --- | --- |
| `ProfileReplaceRequest` | `display_name`, `birth_date`, `gender`, `native_language`; owner/onboarding flag 금지 |
| `LanguageReplaceRequest` | `display_language:'ko'|'en'` |
| `TermsReplaceRequest` | `consents:[{consent_type,policy_version,accepted:true}]` |
| `OnboardingStatus` | `completed:boolean`, `missing_requirements:string[]` |
| `MeResponse` | safe profile, language, active consent status, `onboarding_status` |
| `OnboardingMutationResponse` | 저장된 해당 domain 값 + `onboarding_status` |
| `PersonaSummary/Detail` | catalog ID, 표시 metadata, detail은 allowed scenarios 포함 |
| `ScenarioSummary/Detail` | ID, 표시 metadata; detail은 `max_turns`, ordered required conditions, allowed personas 포함 |

### 5.3 Room·message

| Schema | Fields/constraints |
| --- | --- |
| `RoomCreateRequest` | `practice_type:'free_chat'|'scenario'`, `persona_id`, scenario일 때 `scenario_id`; owner/status 금지 |
| `Room` | `id`, practice/catalog refs, `status`, `turn_count`, `ended_reason|null`, timestamps |
| `RoomDetail` | `Room` + safe relationship/situation/goal + interview configuration ref nullable |
| `MessageCreateRequest` | `content:string`, `input_mode:'text'|'voice'`, 면접이면 `current_interview_question_id`; `client_request_id`는 Idempotency-Key와 같은 UUID 사용 |
| `Message` | `id`, `room_id`, `sequence_no`, `sender_type`, `content`, `input_mode`, `delivery_status`, `reply_to_message_id|null`, safe emotion/status, timestamps |
| `MessageAccepted` | `message:Message`, `job:JobRef` |
| `RepeatRequest` | `recommended_expression:string` |

### 5.4 Feedback·audio·result

| Schema | Fields/constraints |
| --- | --- |
| `FeedbackScore` | category 4종, integer score 0..25, max 25, strength/suggestion/original/recommended text |
| `FeedbackEmotion` | label, percentage, sort order 1..3, source text/voice, safe evidence/impression |
| `FeedbackResponse` | `status:'processing'|'ready'|'partial'|'failed'`, overall 0..100|null, summary|null, scores, emotions, retryable error|null |
| `AudioAccessResponse` | `status:'processing'|'ready'|'failed'`, `signed_url|null`, `expires_at|null`, audio type; storage path 금지 |
| `SessionResultSummary` | `id`, `attempt_no`, `status`, `missing_categories`, `created_at` |
| `ResultItem` | item/category/title/original/recommended/explanation/evidence/source_document_id|null/order |
| `InterviewEvaluationScore` | 고정 category 5종, integer score 1..20, max 20, strength/suggestion/evidence |
| `InterviewEvaluation` | `status:'succeeded'|'partial'|'failed'`, `overall_score:5..100|null`, summary, scores, `missing_categories` |
| `SessionResult` | summary fields, items, safe source refs, 면접이면 `interview_evaluation`; hiring pass/fail 판정 금지 |
| `DomainJobAccepted` | target `DomainRef`, `job:JobRef` |

면접 평가 category는 `question_understanding_fit`, `answer_structure`,
`specificity_evidence`, `job_fit_problem_solving`, `delivery_attitude`의 다섯 항목으로
고정한다. 각 점수는 1~20 정수이며 다섯 점수가 모두 존재할 때만 `overall_score`를 단순
합계로 계산한다. 하나 이상 누락되면 `status='partial'`, `overall_score=null`이고 누락 항목을
`missing_categories`에 기록한다. 다섯 항목이 모두 누락되면 `status='failed'`다.

### 5.5 Interview

| Schema | Fields/constraints |
| --- | --- |
| `InterviewSetupCreateRequest` | `desired_role:string` 1..200자, `application_type:string|null` 최대 100자; owner/status/progress 금지 |
| `InterviewSetup` | `id`, `desired_role`, `application_type|null`, `status`, `preparation_progress`; owner ID 비노출 |
| `DocumentUploadRequest` | file max 10MB. `resume`·`self_introduction`은 PDF/DOCX, `portfolio`는 PDF만 허용. `document_type:'resume'|'portfolio'|'self_introduction'`; client Storage key 금지 |
| `InterviewDocument` | `id`, type, safe original filename, MIME, size, version, current, upload/analysis status; storage path·raw text 금지 |
| `AnalysisAccepted` | `analysis_id`, `document_id`, `document_version`, `job` |
| `InterviewAnalysis` | ids/version/status, normalized extracted sections, citation/source refs, safe error|null; vectors·raw Provider response 금지 |
| `InterviewConfigurationGenerateRequest` | current `analysis_ids`, confirmed interview conditions, requested question count 1..10 |
| `InterviewConfigurationRegenerateRequest` | confirmed changed conditions and/or question count; owner/version fields 금지 |
| `ConfigurationAccepted` | `configuration_id`, `version_no`, `job` |
| `InterviewConfiguration` | id/version/status, document version snapshot, analysis refs, question count, safe error|null |
| `InterviewQuestion` | id, sequence 1..10, text, type, required, source refs, evaluation focus |
| `InterviewQuestionList` | configuration ref/version/status, final ordered questions |

## 6. 상태 전이와 side effect

| Aggregate | 허용 핵심 전이 | API/Worker 책임 |
| --- | --- | --- |
| Onboarding | incomplete → completed | complete endpoint만 server validation 후 전이 |
| Room | created/in_progress → completed 또는 failed | Service가 turn/성공조건/면접질문 판정; 종료 시 result record+Job 자동 생성 |
| Job | queued→processing; processing→queued/succeeded/failed/cancelled | Worker가 domain 상태와 한 transaction에서 전이; terminal immutable |
| AI/emotion/document | processing→succeeded/failed; retryable failed→processing | Job 성공/실패와 동기화하며 API retry는 기존 domain row+새 Job·처리 토큰을 사용 |
| Audio | processing→ready/failed | ready 연결 확정 뒤 old object 삭제 |
| Feedback | processing→ready/partial/failed | 가능한 부분 결과 보존 |
| Configuration | processing→ready→in_progress→completed; failed/invalidated | generation/regeneration과 room 생성을 server가 판정 |
| Result | processing→partial/succeeded/failed | retry는 같은 result row+새 Job |
| Idempotency | in_progress→completed/failed; retryable failed→CAS in_progress | reconcile-first; terminal safe snapshot 불변 |

삭제·교체·회원탈퇴는 queued Job cancel, queue cleanup, Worker의 provider 호출 전/저장 전 owner/resource/version 재검증, stale result discard 순서로 처리한다. 범용 user cancel endpoint는 없다.

## 7. 계층별 호출 계약

| 흐름 | API | Service | Repository/adapter |
| --- | --- | --- | --- |
| 일반 owner 조회 | Bearer 검증·DTO | 접근 가능 action 판정 | owner predicate를 포함한 단일 query; 미소유/미존재 동일 None |
| create/action | header/body 검증 | idempotency claim, domain 판정, transaction 소유 | idempotency/domain 저장, 필요 시 Job publisher와 pgmq send |
| async Worker | HTTP 없음 | job type orchestration·deadline/retry | target owner/version 재조회, Provider adapter, domain+Job 원자 갱신 |
| 파일 | multipart streaming | MIME/parser/text threshold, lifecycle | private Storage adapter + metadata Repository; signed URL은 조회 시만 생성 |
| RAG | request eligibility | retrieval/insufficient evidence 판정 | pgvector owner/version prefilter, Provider adapter에 근거 chunk만 전달 |

Auth dependency는 검증된 `jwt.sub`만 아래 계층으로 전달한다. Provider adapter는 vendor response를 Pydantic 결과로 바꾸며 Service가 raw vendor payload를 해석하지 않는다.

## 8. 비기능·보안 계약

- CORS는 `CORS_ALLOWED_ORIGINS`의 정확한 scheme+host+port만 허용한다. Header는 실제 사용하는 `Authorization`, `Content-Type`, `Idempotency-Key`만 허용한다.
- Upload는 `UploadFile` streaming, extension+magic MIME+parser 검증을 모두 통과해야 한다. DOCX macro/비정상 archive를 거부하고 문서 실행은 하지 않는다.
- 로그는 JSON이며 request_id/job_id, 안전한 internal user ID, route/job type/status/duration/provider error code만 남긴다.
- Provider 전송 오류는 총 3회(최초+2 retry), exponential backoff+jitter, deadline 우선이다. Structured output repair는 같은 Job에서 정확히 1회다.
- OpenAI 호출은 지원 범위에서 `store=false`, 장기 보존/학습 비활성 account 설정을 점검한다.
- Voice input 공식 지원은 최신 Chrome/Edge desktop+Android다. Safari/Firefox/iOS는 text fallback이다.

## 9. 구현 금지 및 범위 밖

- 이 문서는 FastAPI route/service/repository 코드, SQL table/RLS, Alembic migration, pgmq consumer, Provider prompt를 구현하지 않는다.
- Browser의 app table/queue 직접 CRUD, 공개 Storage URL, raw path/type assertion, service role 노출은 금지한다.
- OAuth/account linking, OCR, ClamAV, Redis/Celery, SSE/WebSocket, generic cancel API, admin API는 MVP 범위 밖이다.
- Cloud 배포·운영은 범위 밖이며 React/FastAPI/Python worker의 로컬 실행과 원격 Supabase/Gemini/OpenAI만 전제한다.
- 측정 전 임의 숫자를 만들지 않는다: pagination limit, user queue limit, worker concurrency, RAG threshold, context summary trigger, document minimum text chars, worker heartbeat TTL, idempotency lease/retention. 모두 기본값 없는 필수 환경변수다. `session_result_generation`은 확정된 60초 deadline·최대 3회 시도를 사용한다.

## 10. 근거 추적표

| 계약 영역 | PRD | 화면기획서 | ERD | 아키텍처 |
| --- | --- | --- | --- | --- |
| 온보딩·계정 | FR-01, 개인정보 삭제 | 온보딩/M08 | profiles/consent ownership | 6, 12.1 |
| 대화·부분 실패 | FR-03~08 | C/T 흐름, 독립 처리 상태 | room/message/AI/emotion | 8, 12.2~3 |
| TTS·피드백 | FR-06~07 | timeout/retry/current audio | message_audio/turn_feedback | 7~8, 12.3 |
| 결과 snapshot | 결과·재도전 요구 | 결과/목록/삭제 화면 | session_results/result_items | 12.3 |
| 문서·RAG | 면접 자료 분석 | upload/분석/면접 흐름 | documents/analyses/config/questions | 9, 12.4 |
| Job·멱등성 | NFR timeout/보존 | processing UX | processing_jobs/idempotency_records | 8, 11 |
| 접근 제어 | 개인정보·소유 범위 | 삭제 안내 | owner chain/RLS | 6.3 matrix |

## 11. 자체 검수

- [x] `/api/v1`, Bearer, error envelope, idempotency, cursor 계약 포함
- [x] Health, onboarding, catalog, rooms/messages, 감정·피드백·TTS retry, jobs/results, documents/analysis, configuration/questions/practice, account deletion 포함
- [x] 모든 endpoint에 operationId, method/path, auth, request/response, status/error, owner chain 기재
- [x] 7종 Job과 stage/error/result_resource, 2초 polling, 자동 result 생성 포함
- [x] `processing_jobs`와 `idempotency_records`의 최신 ERD 계약 반영
- [x] API→Service→Repository→Supabase 판정 경계와 uniform 404 포함
- [x] raw 민감정보·signed URL snapshot·Provider 원본 비노출 포함
- [x] 미확정 수치를 default로 발명하지 않음

### 구현 전 기계 검증 항목

1. 이 문서의 operationId와 최종 OpenAPI artifact가 1:1인지 검사한다.
2. Idempotency action allowlist에는 실제 존재하는 create/action/delete operationId만 seed한다.
3. Generated TypeScript client가 raw path 없이 모든 endpoint를 호출하는지 검사한다.
4. 각 owner chain에 owner/non-owner/nonexistent 통합 테스트를 둔다.
5. `session_result_generation`의 60초·최대 3회 정책이 누락되거나 비활성화되면 readiness와 enqueue가 fail-closed인지 검사한다.
