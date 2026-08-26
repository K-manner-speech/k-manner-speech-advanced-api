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
`vector` extension, 6개 queue, timeout policy 7종, 설정, base queue 3종의 worker heartbeat를
검사합니다.

현재 API에는 active Auth session 검증, 인증·온보딩·회원 탈퇴·카탈로그·대화·피드백·감정·TTS·결과·면접 문서·면접 구성·Job
조회가 포함됩니다. Worker는 일곱 Job 유형, 문서 chunk/embedding RAG, 면접 5항목 평가를
처리합니다. 회원 탈퇴는 private Storage user-prefix object, Job/queue, DB/vector와 Supabase Auth 사용자를 즉시 영구 삭제하며 완료 뒤 멱등 snapshot을 보존하지 않습니다.

## 로컬 면접 시연

원격 Supabase schema에 `supabase/migrations/*.sql`을 순서대로 적용하고, `.env`에
`DATABASE_URL`, Supabase 설정, `OPENAI_API_KEY`, `OPENAI_INTERVIEW_MODEL`을 채웁니다.
API와 base queue Worker 세 개는 서로 다른 PowerShell 창에서 실행해야 합니다.

```powershell
# 창 1: API
$env:UV_CACHE_DIR='.uv-cache'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload

# 창 2: 대화 응답 worker
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m worker.conversation_text

# 창 3: 감정·TTS·피드백·결과 worker
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m worker.interactive_ai

# 창 4: 문서 분석 및 면접 질문 생성 worker
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m worker.document_analysis
```

Worker 실행 전 `.env`에는 `WORKER_VISIBILITY_TIMEOUT_SECONDS`를 포함한 필수 설정과 기능별
Provider model ID가 모두 있어야 합니다. embedding model은 DB의 `vector(3072)` 계약과 맞는
`text-embedding-3-large`만 허용합니다.

Swagger UI에서 Bearer token과 매 요청의 `Idempotency-Key`(새 UUID)를 입력하고 다음 순서로
시연합니다.

1. `POST /api/v1/interview-setups`
2. `POST /api/v1/interview-documents` (`resume`, PDF 또는 DOCX)
3. `POST /api/v1/interview-documents/{document_id}/analyze`
4. 분석 조회 결과가 `succeeded`가 될 때까지 조회
5. `POST /api/v1/interview-configurations`
6. 구성 조회 결과가 `ready`가 된 후 질문 목록 조회
7. 면접 practice room을 생성하고 질문의 `sequence` 순서대로만 답변 전송

원격 시연용 계정 값은 `.env.test.example`을 `.env.test`로 복사해 로컬에만 보관합니다.
`.env.test`는 Git에서 제외됩니다. 시연 후 생성한 setup, document, configuration, room과
Storage 객체는 해당 테스트 계정 소유 데이터만 정리합니다.
