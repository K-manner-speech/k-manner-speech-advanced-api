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
`vector` extension, 6개 queue, timeout policy 7종, 설정을 검사합니다. Worker heartbeat는
`REQUIRED_WORKER_QUEUES`에 지정된 base queue만 검사하며 로컬 기본값은 현재 구현된
`["document_analysis"]`입니다. 팀원이 `conversation_text` 또는 `interactive_ai` worker를
구현하면 해당 base queue 이름을 배열에 추가합니다. DLQ 이름은 이 설정에 넣지 않습니다.

JWT 발급 서버와 로컬 PC 시계의 짧은 차이는 `JWT_LEEWAY_SECONDS=5`로 허용합니다. 음수는
설정 오류이며, 필요 이상으로 크게 늘리지 않습니다.

현재 API에는 인증·온보딩·카탈로그·대화·피드백·감정·TTS·결과·면접 문서·면접 구성·Job
조회가 포함됩니다. 계정 완전 삭제는 vector 삭제 계약, 면접 5항목 평가는 점수 DTO/DB 계약이
확정될 때까지 보류합니다.

## 로컬 면접 시연

원격 Supabase schema에 `supabase/migrations/*.sql`을 순서대로 적용하고, `.env`에
`DATABASE_URL`, Supabase 설정, `OPENAI_API_KEY`, `OPENAI_INTERVIEW_MODEL`,
`OPENAI_EMBEDDING_MODEL`을 채웁니다. 현재 worker와 `document_chunks.embedding` 계약은
3072차원이므로 로컬에서는 `OPENAI_EMBEDDING_MODEL=text-embedding-3-large`,
`OPENAI_EMBEDDING_DIMENSIONS=3072`를 사용합니다.
API와 문서 분석 worker는 서로 다른 PowerShell 창에서 실행해야 합니다.

```powershell
# 창 1: API
$env:UV_CACHE_DIR='.uv-cache'
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload

# 창 2: 문서 분석 및 면접 질문 생성 worker
$env:UV_CACHE_DIR='.uv-cache'
uv run python -m worker.document_analysis
```

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
