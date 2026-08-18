# K-Manner Speech 프로젝트 구조 컨벤션 v5

> 이 문서는 `k-manner-speech-api`와 `k-manner-speech-front`를 위한 최종 목표 구조다. 구조 이동, 제품 도메인 재명명, 도구 전환은 각각 독립된 변경으로 관리한다.

## 0. 확정한 결정

| 항목 | 결정 | 근거 |
| --- | --- | --- |
| 저장소 | Front/API 2개 저장소 유지 | 배포·권한·릴리스 주기 분리 |
| Front | React + TypeScript + Vite 유지 | 앱형 UI에 SSR·SEO 요구가 확정되지 않음 |
| Front 패키지 관리 | npm과 `package-lock.json` 유지 | 현재 저장소와 일치 |
| Front 루트 | `web/` 중첩 유지 | 기존 경로와 호환 |
| Back | FastAPI + SQLAlchemy 유지 | 현재 구현과 일치 |
| Python 런타임 | **Python 3.11.15** | 팀의 고정 실행 환경 |
| Python 가상환경 | **`genai/`** | API 저장소 루트의 로컬 개발 가상환경 이름 |
| DB 마이그레이션 | Alembic 단일 기준 | 모델과 DB 변경 이력의 단일 소유자 |
| DB 연결 | 서버 전용 `DATABASE_URL`로 Supabase pooler의 Postgres 사용자에 접속 | SQLAlchemy 연결 방식과 일치 |
| 소유권 통제 | 서비스 계층에서 검증된 사용자 ID로 모든 사용자 소유 쿼리를 제한 | 요청별 JWT를 DB 세션에 주입하지 않음 |
| RLS | Data API 직접 접근 제한용, 서버 DB 쿼리의 백업 통제로 가정하지 않음 | DB 역할과 요청 컨텍스트가 별개 |
| Repository | 선택적 도입 | 단순 CRUD에 불필요한 계층을 만들지 않음 |
| AI | `app/ai/`는 공급자·프롬프트, `app/services/`는 유스케이스 | 외부 구현과 도메인 규칙 분리 |
| Feature 참조 | `index.ts` 공개 API만 허용, deep import·순환 참조 금지 | 기능 응집과 재사용의 균형 |
| 제품 도메인명 | `rooms`, `chat`, `room_conversation`, `web_speech` 유지 | 구조 작업 중 제품 용어를 암묵적으로 변경하지 않음 |

`rooms/chat → practice`, `web_speech → voice`, `web/` 평탄화, Next.js 전환은 별도 ADR·영향 분석·전용 PR이 승인될 때만 수행한다.

## 1. Python 개발 환경

### 1.1 표준 런타임과 가상환경

API 저장소의 개발·테스트·CI 런타임은 Python **3.11.15**로 고정한다. 로컬 가상환경 디렉터리는 API 저장소 루트의 `genai/`를 사용하며, 커밋하지 않는다.

```text
k-manner-speech-api/
├── .python-version             # 3.11.15
├── genai/                      # 로컬 가상환경, .gitignore에 포함
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

가상환경 생성과 의존성 설치의 표준 명령은 다음과 같다.

```bash
uv python install 3.11.15
uv venv --python 3.11.15 genai
source genai/bin/activate
uv pip install -r requirements-dev.txt
python --version
```

마지막 명령은 반드시 `Python 3.11.15`를 출력해야 한다. `genai/`은 `.gitignore`에 추가하며, CI는 이 디렉터리를 재사용하지 않고 Python 3.11.15에서 매번 깨끗한 환경을 만든다.

### 1.2 Python 3.11.15 전환 조건

현재 API 의존성 파일은 Python 3.14.3 검증 이력이 있고, 기존 `uv.lock`은 Python 3.14 이상을 요구한다. 따라서 3.11.15를 표준으로 확정하는 PR에는 다음을 포함한다.

1. `pyproject.toml` 또는 팀의 단일 의존성 메타데이터에 지원 범위 `>=3.11,<3.12`를 명시한다.
2. Python 3.11.15의 깨끗한 `genai/` 환경에서 런타임·개발 의존성을 설치한다.
3. `ruff check app tests`와 전체 `pytest`를 실행한다.
4. `uv.lock`을 유지한다면 3.11.15 지원 범위로 재생성·커밋한다. `requirements*.txt`를 표준으로 유지한다면 `uv.lock`을 별도 진실 원본처럼 사용하지 않는다.
5. README, CI, Docker 기반 이미지의 Python 버전을 모두 3.11.15로 맞춘다.

의존성 선언과 잠금 파일의 기준은 하나여야 한다. `requirements*.txt`와 `uv.lock`이 서로 다른 Python 범위를 가리키는 상태를 유지하지 않는다.

## 2. 즉시 보안 조치

`DATABASE_URL`과 Supabase 서비스 역할 키를 소스 코드의 기본값으로 두지 않는다. 실제 비밀값이 소스·Git 이력·CI 로그·문서에 포함된 적이 있다면 DB 비밀번호와 서비스 역할 키를 즉시 교체한다. 환경변수가 누락되면 애플리케이션은 시작 시 명시적으로 실패해야 한다.

## 3. 공통 원칙

1. 상위 계층은 하위 계층을 사용할 수 있지만 하위 계층은 상위 계층을 import하지 않는다.
2. Back은 계층 경계를 유지하고 Front는 기능 단위 응집을 우선한다.
3. 의미와 변경 주기까지 같을 때만 공용 모듈로 승격한다.
4. 파일 길이는 분리 신호일 뿐 강제 기준이 아니다.
5. 구조 이동, 제품 용어 변경, API 변경은 같은 PR에 섞지 않는다.
6. 생성 코드, 빌드 산출물, 비밀값은 사람이 관리하는 소스와 분리한다.

## 4. 전체 저장소 구조

### API 저장소

```text
k-manner-speech-api/
├── .python-version             # 3.11.15
├── app/
│   ├── main.py
│   ├── core/                    # 설정, 인증, DB, 공통 예외
│   ├── routers/                 # HTTP 엔드포인트
│   ├── schemas/                 # Pydantic API 계약
│   ├── services/                # 유스케이스와 도메인 규칙
│   ├── models/                  # SQLAlchemy 영속성 모델
│   ├── repositories/            # 필요한 도메인만 사용하는 쿼리 경계
│   └── ai/                      # 프롬프트와 AI 공급자 구현
├── migrations/                  # Alembic 변경 이력
├── tests/
├── scripts/
├── docs/
├── .github/workflows/
├── .env.example
├── alembic.ini
├── Dockerfile
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
└── uv.lock                      # 유지 시 Python 3.11.15 범위와 일치
```

### Front 저장소

```text
k-manner-speech-front/
├── scripts/
└── web/
    ├── public/
    ├── src/
    │   ├── main.tsx
    │   ├── index.css
    │   ├── app/
    │   ├── features/
    │   ├── components/
    │   ├── api/
    │   ├── store/
    │   ├── lib/
    │   ├── assets/
    │   ├── stories/
    │   └── test/
    ├── e2e/
    ├── .storybook/
    ├── .env.example
    ├── package.json
    ├── package-lock.json
    ├── tsconfig.json
    ├── vite.config.ts
    └── README.md
```

Front 내부 경로는 별도 언급이 없으면 `web/` 기준이다.

## 5. 백엔드 구조

```text
app/
├── main.py
├── core/
│   ├── config.py               # 환경변수와 Settings
│   ├── auth.py                 # Supabase JWT 사용자 검증
│   ├── db.py                   # DATABASE_URL 기반 엔진과 세션
│   ├── errors.py               # 공통 예외와 전역 핸들러
│   └── dependencies.py         # 인증·페이징 등 공통 Depends
├── routers/
│   ├── health.py
│   ├── auth.py
│   ├── catalog.py
│   ├── chat.py
│   ├── rooms.py
│   ├── room_conversation.py
│   └── web_speech.py
├── schemas/
│   ├── auth.py
│   ├── catalog.py
│   ├── chat.py
│   ├── rooms.py
│   ├── room_conversation.py
│   └── speech.py
├── services/
│   ├── catalog.py
│   ├── room_conversation.py
│   ├── rooms/                  # 여러 방 유스케이스가 있을 때만 패키지화
│   ├── conversation/
│   └── feedback/
├── models/
│   ├── catalog.py
│   ├── user.py
│   └── chat/
│       ├── room.py
│       ├── message.py
│       └── feedback.py
├── repositories/              # 선택 사항
│   └── rooms.py
└── ai/
    ├── interfaces.py
    ├── prompts/
    └── providers/              # 실제 구현과 결정적인 demo 구현
```

| 계층 | 책임 |
| --- | --- |
| `routers` | 경로, 인증 의존성, 입력 검증, HTTP 상태 코드 |
| `schemas` | 요청·응답 DTO와 검증 |
| `services` | 유스케이스, 소유권 검사, 트랜잭션 흐름 |
| `repositories` | 복잡·반복 SQLAlchemy 쿼리 |
| `models` | 테이블, 관계, DB 제약 |
| `ai` | 프롬프트, 인터페이스, 공급자 구현 |
| `core` | 설정, 인증 검증, DB 연결, 공통 예외 |

```text
main
  └── routers
        ├── schemas
        └── services
              ├── repositories ── models
              ├── models
              ├── ai
              └── core
```

- `services`와 `schemas`는 `routers`를 import하지 않는다.
- 모든 사용자 소유 쿼리는 서비스 계층에서 검증된 사용자 ID로 필터링한다.
- 단순 CRUD는 서비스가 세션을 직접 사용할 수 있다.
- 복잡한 쿼리·반복 조회·교체 가능한 저장 경계가 필요할 때만 Repository를 도입한다.
- 실제 AI 호출은 `ai/interfaces.py` 뒤에 두고 테스트에서는 demo 구현으로 교체한다.

## 6. 프론트엔드 구조

```text
web/src/
├── main.tsx
├── index.css
├── app/
│   ├── App.tsx
│   ├── router.tsx
│   ├── routeMeta.ts
│   └── providers/
├── features/
│   └── <feature>/
│       ├── components/
│       ├── hooks/
│       ├── api.ts
│       ├── store.ts
│       ├── types.ts
│       └── index.ts            # 다른 모듈에 허용하는 공개 API
├── components/
│   ├── ui/
│   └── shell/
├── api/
│   ├── http.ts
│   └── generated/              # OpenAPI 생성 타입, 직접 수정 금지
├── store/
├── lib/
├── assets/
├── stories/
└── test/
```

1. `app/`은 라우터와 Provider를 조립하고 화면 로직은 `features/`에 둔다.
2. 기능 전용 컴포넌트·Hook·상태·타입은 해당 Feature 안에 둔다.
3. 다른 Feature의 내부 파일을 deep import하지 않고 `index.ts` 공개 API만 사용한다.
4. Feature 간 순환 참조를 금지한다.
5. 도메인을 모르는 공용 UI만 `components/ui/`로 승격한다.
6. HTTP 요청은 공통 `api/http.ts`와 기능별 `features/<feature>/api.ts`를 통한다.
7. Supabase 클라이언트는 인증 세션에만 사용하고 서비스 테이블을 직접 조회하지 않는다.

## 7. CORS·쿠키·CSRF

- 허용 Origin은 API 환경변수에 명시하고 로컬·스테이징·운영을 분리한다.
- 쿠키나 `credentials` 요청에서는 와일드카드 Origin을 사용하지 않는다.
- 쿠키의 `Secure`, `HttpOnly`, `SameSite`, `Domain` 정책을 환경별로 문서화한다.
- 상태 변경 요청에는 인증 방식에 맞는 CSRF 방어를 적용한다.
- 브라우저에는 publishable/anon 키만 전달하고 DB·서비스 역할 자격 증명은 전달하지 않는다.

## 8. API 계약 관리

```text
Pydantic schema
    → 버전이 지정된 OpenAPI artifact
        → openapi-typescript
            → web/src/api/generated/
                → typecheck와 build
```

1. API CI가 OpenAPI JSON을 생성하고 API 커밋 SHA 또는 릴리스 버전을 기록한다.
2. Front는 고정된 artifact 버전에서 타입을 생성한다.
3. Front CI는 재생성 결과와 커밋된 타입의 차이를 검사한다.
4. 경로·필드 삭제, 타입 변경, required 필드 추가 같은 breaking 변경은 CI를 실패시킨다.
5. 필드·선택적 엔드포인트 추가 같은 non-breaking 변경은 CI를 통과시키되 PR에 경고를 남긴다.
6. `contract-check`가 기본 브랜치 CI에 들어오는 시점부터 새 수동 API 타입을 금지하고, 기존 수동 타입은 해당 스프린트 안에 생성 타입으로 전환한다.

## 9. 데이터베이스와 인증 보안

| 자격 증명 | 사용 위치 | 규칙 |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy의 Postgres 직접 연결 | 서버 환경에만 보관, 코드 기본값 금지 |
| `SUPABASE_SERVICE_ROLE_KEY` | 서버가 Supabase API를 관리자 권한으로 호출할 때만 사용 | 서버 환경에만 보관, 브라우저 전달 금지 |
| publishable/anon key | 브라우저 Supabase Auth 세션 | 서비스 테이블 직접 접근 권한을 전제로 하지 않음 |

현재 구조는 요청별 사용자 JWT를 SQLAlchemy 세션에 전달하지 않는다. 따라서 서비스 계층의 소유권 검사가 FastAPI 경로의 실질적인 접근 통제다.

RLS는 노출 스키마의 Data API에서 anon/authenticated 직접 접근을 제한한다. 서버 DB 쿼리의 소유권 누락을 막는 장치로 가정하지 않는다. Supabase 서비스 역할은 RLS를 우회하므로 서버 전용으로 관리해야 한다. [Supabase RLS 문서](https://supabase.com/docs/guides/database/postgres/row-level-security)

Alembic을 DB 변경 이력의 단일 기준으로 사용한다.

1. 모델, 마이그레이션, RLS·GRANT·Data API 노출 정책은 같은 PR에서 검토한다.
2. 노출 스키마의 테이블에는 RLS를 활성화한다.
3. Front가 직접 사용하지 않는 서비스 테이블은 `anon`·`authenticated`의 불필요한 권한을 회수하거나 Data API 노출을 제한한다.
4. 같은 스키마 변경을 Alembic과 별도 수동 SQL 파일 양쪽에서 중복 관리하지 않는다.

## 10. 테스트와 CI

```text
API
  lint               uv run ruff check app tests
  unit-test          uv run pytest tests/unit
  integration-test   uv run pytest tests/integration tests/contract
  migration-check    Alembic head와 모델 메타데이터 검증
  openapi-check      OpenAPI 생성과 breaking 변경 검사
  image-build        Docker 이미지 빌드

Front (web/ 작업 디렉터리)
  lint               npm run lint
  typecheck          npm run typecheck
  contract-check     고정 OpenAPI 버전의 생성 타입 검증
  unit-test          npm run test
  e2e                npm run e2e
  build              npm run build
```

API CI와 Docker 이미지는 Python 3.11.15를 사용한다. E2E와 단위 테스트는 준비 환경과 실패 원인이 다르므로 별도 CI 단계로 운영한다.

## 11. 환경변수와 적용 순서

```text
k-manner-speech-api/.env.example
k-manner-speech-front/web/.env.example
```

- 실제 `.env`, `.env.local`, `genai/`은 커밋하지 않는다.
- 브라우저 번들에 포함되는 `VITE_*`에는 비밀값을 넣지 않는다.
- 새 변수는 예제 파일과 README에 함께 추가한다.

적용 순서:

1. 노출됐을 수 있는 DB·서비스 역할 자격 증명을 교체하고 소스 코드 기본 비밀값을 제거한다.
2. Python 3.11.15용 `genai/` 환경을 만들고 의존성 설치·린트·테스트를 검증한다.
3. Python 지원 범위, 잠금 파일, CI, Docker, README를 3.11.15로 통일한다.
4. 동작 변경 없이 파일·import만 정리하고 기존 테스트·빌드를 통과시킨다.
5. `app/ai/`, 선택적 Repository, OpenAPI 생성 자동화를 각각 독립 작업으로 도입한다.
6. API 소유권 통합 테스트와 Data API 권한 검토를 추가한다.
7. `web/` 평탄화와 제품 도메인 재명명은 각각 별도 ADR과 전용 PR로 처리한다.

## 12. 저장소별 소유권과 변경 판단

| 대상 | 소유 저장소 |
| --- | --- |
| HTTP API와 OpenAPI 원본 | `k-manner-speech-api` |
| SQLAlchemy 모델, Alembic, RLS·GRANT·Data API 정책 | `k-manner-speech-api` |
| AI·TTS·외부 공급자 비밀값 | `k-manner-speech-api` |
| 페이지, UI, 브라우저 상태 | `k-manner-speech-front` |
| Supabase 사용자 세션 | `k-manner-speech-front` |
| OpenAPI 생성 TypeScript 타입 | `k-manner-speech-front` |

새 계층이나 패키지는 다음 중 하나에 명확히 “예”라고 답할 수 있을 때만 추가한다.

- 기존 모듈과 변경 이유가 다른가?
- 의미와 변경 주기가 같은 코드가 실제로 반복되는가?
- 외부 시스템 경계를 테스트에서 교체해야 하는가?
- 현재 결합도 때문에 리뷰와 테스트가 어려운가?
- 접근 권한, 트랜잭션 또는 배포 단위를 따로 관리해야 하는가?

구조의 목표는 디렉터리를 많이 만드는 것이 아니라 **기능 변경의 영향 범위를 예측 가능하게 만드는 것**이다.
