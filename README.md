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

```bash
source genai/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

- Swagger UI: `http://127.0.0.1:8010/docs`
- Liveness: `GET http://127.0.0.1:8010/api/v1/health/live`
- Readiness: `GET http://127.0.0.1:8010/api/v1/health/ready`

`.env.example`의 항목을 `.env`에 채워야 합니다. 측정 대상 값에는 코드 기본값이 없으며,
누락 시 readiness가 안전하게 `503 SERVICE_NOT_READY`를 반환합니다. Ready는 DB, `pgmq`와
`vector` extension, 6개 queue, timeout policy 7종, 설정, base queue 3종의 worker heartbeat를
검사합니다.

현재 API에는 인증·온보딩·카탈로그·대화·피드백·감정·TTS·결과·면접 문서·면접 구성·Job
조회가 포함됩니다. 계정 완전 삭제는 vector 삭제 계약, 면접 5항목 평가는 점수 DTO/DB 계약이
확정될 때까지 보류합니다.
