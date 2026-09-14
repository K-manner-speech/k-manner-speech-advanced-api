# k-manner-speech-advanced

K-Manner Speech의 FastAPI 백엔드와 Supabase migration을 관리하는 저장소입니다.

## 개발 환경

- Python 3.11.15
- FastAPI
- Pydantic v2
- Supabase Postgres migration: `supabase/migrations/*.sql`

```bash
uv python install 3.11.15
uv venv --python 3.11.15 genai
source genai/bin/activate
uv pip install -r requirements-dev.txt
pytest
ruff check app worker tests
mypy app worker
```

## 로컬 API 실행

PowerShell에서 프로젝트 루트로 이동한 뒤 실행합니다.

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

- Swagger UI: `http://127.0.0.1:8010/docs`
- Liveness: `GET http://127.0.0.1:8010/api/v1/health/live`
- Readiness: `GET http://127.0.0.1:8010/api/v1/health/ready`

`.env.example`의 항목을 `.env`에 채워야 합니다. 측정 대상 값에는 코드 기본값이 없으며,
누락 시 readiness가 안전하게 `503 SERVICE_NOT_READY`를 반환합니다. Ready는 DB, `pgmq`와
`vector` extension, 8개 queue, timeout policy 8종, 설정을 검사합니다. Worker heartbeat는
`REQUIRED_WORKER_QUEUES`에 지정된 base queue만 검사하며 로컬 기본값은 현재 구현된
`["conversation_text","interactive_ai","evaluation_ai","document_analysis"]`입니다. 네
worker를 모두 실행해야 readiness가 통과하며, DLQ 이름은 이 설정에 넣지 않습니다.

`DATABASE_URL`은 Supabase 풀러의 transaction mode 포트 `6543`을 씁니다. session mode(`5432`)는 동시
클라이언트가 15개로 제한되어 API와 worker 네 개를 함께 띄우면 `FATAL: (EMAXCONNSESSION) max clients
reached in session mode`로 DB 에 아예 붙지 못합니다. 이때 readiness 는 연결 실패를 개별 항목 고장과
구분하지 못해 `failed_checks`에 6개가 모두 나오므로, 전부 실패로 보이면 먼저 포트와 커넥션 한도를
확인합니다. 커넥션 한도는 Supabase 프로젝트 전체 기준이라 다른 팀원이 붙어 있으면 함께 차감됩니다.

JWT 발급 서버와 로컬 PC 시계의 짧은 차이는 `JWT_LEEWAY_SECONDS=5`로 허용합니다. 음수는
설정 오류이며, 필요 이상으로 크게 늘리지 않습니다.

현재 API에는 active Auth session 검증, 인증·온보딩·회원 탈퇴·카탈로그·대화·피드백·감정·TTS·결과·면접 문서·면접 구성·Job
조회가 포함됩니다. Worker는 여덟 Job 유형, 문서 chunk/embedding RAG, 면접 5항목 평가를
처리합니다. 회원 탈퇴는 private Storage user-prefix object, Job/queue, DB/vector와 Supabase Auth 사용자를 즉시 영구 삭제하며 완료 뒤 멱등 snapshot을 보존하지 않습니다.

## 로컬 면접 시연

원격 Supabase schema에 `supabase/migrations/*.sql`을 순서대로 적용하고, `.env`에
`DATABASE_URL`, Supabase 설정, `OPENAI_API_KEY`, `OPENAI_INTERVIEW_MODEL`,
`OPENAI_EMBEDDING_MODEL`을 채웁니다. 현재 worker와 `document_chunks.embedding` 계약은
3072차원이므로 로컬에서는 `OPENAI_EMBEDDING_MODEL=text-embedding-3-large`,
`OPENAI_EMBEDDING_DIMENSIONS=3072`를 사용합니다.
API와 base queue Worker 네 개는 서로 다른 PowerShell 창에서 실행해야 합니다.

```powershell
# 창 1: API
$env:UV_CACHE_DIR='.uv-cache'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload

# 창 2: 대화 응답 worker
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m worker.conversation_text

# 창 3: 감정·TTS worker
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m worker.interactive_ai

# 창 4: 피드백·결과·목표 판정 worker
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m worker.evaluation_ai

# 창 5: 문서 분석 및 면접 질문 생성 worker
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m worker.document_analysis
```

Worker 는 코드를 다시 읽지 않습니다. API 는 `--reload` 로 뜨지만 worker 는 시작할 때 읽은
코드로 끝까지 돕니다. 프롬프트(`app/ai/prompts`), AI 계약(`app/ai/schemas.py`), `worker/` 를
고쳤다면 해당 worker 를 종료하고 다시 띄워야 반영됩니다. 옛 worker 가 살아 있으면 새 worker 와
같은 queue 를 함께 잡아 결과가 번갈아 나오므로, 다시 띄우기 전에 남아 있는 프로세스가 없는지
확인합니다.

```bash
for w in conversation_text interactive_ai evaluation_ai document_analysis; do pkill -f "worker.$w"; done
ps -eo pid,command | grep "[w]orker\."   # 아무것도 남지 않아야 합니다
```

Worker 실행 전 `.env`에는 `WORKER_VISIBILITY_TIMEOUT_SECONDS`를 포함한 필수 설정과 기능별
Provider model ID가 모두 있어야 합니다. embedding model은 DB의 `vector(3072)` 계약과 맞는
`text-embedding-3-large`만 허용합니다.

Swagger UI에서 Bearer token과 매 요청의 `Idempotency-Key`(새 UUID)를 입력하고 다음 순서로
시연합니다.

1. `POST /api/v1/interview-setups`
2. `POST /api/v1/interview-documents` (`resume`, PDF 또는 DOCX)
3. `POST /api/v1/interview-documents/{document_id}/analyze`
4. worker가 문서를 청크하고 embedding을 pgvector에 저장한 뒤, 분석 조회 결과가
   `succeeded`가 될 때까지 조회
5. `POST /api/v1/interview-configurations`
6. worker가 직무·조건 query와 유사한 문서 chunk만 검색해 질문을 생성하고, 구성 조회 결과가
   `ready`가 된 후 질문 목록 조회
7. 면접 practice room을 생성하고 질문의 `sequence` 순서대로만 답변 전송

면접 구성 생성 Job의 현행 deadline은 OpenAI 응답과 RAG 검색 시간을 포함해 180초입니다.

원격 시연용 계정 값은 `.env.test.example`을 `.env.test`로 복사해 로컬에만 보관합니다.
`.env.test`는 Git에서 제외됩니다. 시연 후 생성한 setup, document, configuration, room과
Storage 객체는 해당 테스트 계정 소유 데이터만 정리합니다.

API와 worker가 실행 중이고 `.env.test`에 `API_BASE_URL`, `SUPABASE_TEST_EMAIL`,
`SUPABASE_TEST_PASSWORD`가 설정되어 있다면 다음 순서로 원격 smoke와 정리를 실행합니다.

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv run --with-requirements requirements-dev.txt python -m scripts.remote_demo_smoke
uv run --with-requirements requirements-dev.txt python -m scripts.cleanup_remote_demo
```

Smoke 성공 표시는 `REMOTE_DEMO_OK`입니다. 정리 스크립트는 재사용 가능한 성공 분석 문서를
보존하고, 그 외 시연 중 생성된 room, configuration, 실패·미완료 분석, job, queue message와
Storage 객체를 정리합니다. 정리 결과는 `REMOTE_DEMO_CLEANUP_OK`로 출력됩니다.
