# K-Manner Speech 프로젝트 구조 컨벤션 v4

> 이 문서는 `k-manner-speech-api`, `k-manner-speech-front`의 실제 기술 스택과 DB 연결 방식을 기준으로 한 목표 구조다. 구조 이동, 제품 도메인 재명명, 도구 전환은 서로 다른 변경으로 관리한다.
>
> - API 참고 저장소: <https://github.com/kt-cloud-tech-up-gen-ai/k-manner-speech-api>
> - Frontend 참고 저장소: <https://github.com/kt-cloud-tech-up-gen-ai/k-manner-speech-front>

## 0. 확정한 결정

| 항목 | 결정 | 근거 |
| --- | --- | --- |
| 저장소 | Front/API 2개 저장소 유지 | 배포·권한·릴리스 주기 분리 |
| Front | React + TypeScript + Vite 유지 | 현재 앱형 UI에 SSR·SEO 요구가 확정되지 않음 |
| Front 패키지 관리 | npm과 `package-lock.json` 유지 | 현재 저장소와 일치 |
| Front 루트 | `web/` 중첩 유지 | 기존 경로와 호환, 불필요한 대량 파일 이동 방지 |
| Back | FastAPI + SQLAlchemy 유지 | 현재 구현과 일치 |
| Python 패키지 관리 | `pyproject.toml` + `uv.lock` | 재현 가능한 잠금 관리 |
| 마이그레이션 | Alembic 단일 기준 | 모델과 DB 변경 이력의 단일 소유자 |
| DB 연결 | FastAPI는 서버 전용 `DATABASE_URL`로 Supabase pooler의 프로젝트 전용 Postgres 사용자에 접속 | 실제 `core/db.py` 확인 |
| Supabase 서비스 역할 키 | Supabase API 호출용 서버 비밀값이며 `DATABASE_URL`과 별개 | 실제 환경 검증 코드 확인 |
| 소유권 통제 | 서비스 계층에서 검증된 사용자 ID로 모든 사용자 소유 쿼리를 제한 | 요청별 JWT를 SQLAlchemy 세션에 주입하지 않음 |
| RLS | 노출 스키마의 Data API 직접 접근 보호에 사용, 서버 DB 쿼리의 백업 통제로 가정하지 않음 | 서버 역할·세션 컨텍스트와 별개 |
| Repository | 선택적 도입 | 단순 CRUD에 불필요한 계층을 만들지 않음 |
| AI | `app/ai/`는 공급자·프롬프트, `app/services/`는 유스케이스 | 외부 구현과 도메인 규칙 분리 |
| Feature 참조 | `index.ts` 공개 API는 허용, deep import·순환 참조 금지 | 기능 응집과 재사용의 균형 |
| 제품 도메인명 | `rooms`, `chat`, `room_conversation`, `web_speech` 유지 | 구조 작업 중 제품 용어를 암묵적으로 변경하지 않음 |

`rooms/chat → practice`, `web_speech → voice`, `web/` 평탄화, Next.js 전환은 별도 ADR·영향 분석·전용 PR이 승인될 때만 수행한다.

### 즉시 보안 조치

`DATABASE_URL`과 Supabase 서비스 역할 키를 소스의 기본값으로 두지 않는다. 실제 비밀값이 소스 또는 커밋 이력에 포함된 적이 있다면 DB 비밀번호와 서비스 역할 키를 즉시 교체하고, Git 이력·배포 환경·CI 비밀값을 점검한다. 환경변수가 없으면 애플리케이션은 시작 시 실패해야 한다.

### `web/` 평탄화 체크리스트

평탄화가 승인된 경우에만 동작 변경 없는 전용 PR에서 다음을 함께 갱신한다.

- `package.json`, `package-lock.json`, `.gitignore`
- Vite·TypeScript·Playwright·Storybook 설정
- `.env.example`과 API 타입 생성 출력 경로
- GitHub Actions의 `working-directory`와 배포 플랫폼 Root Directory
- Figma 동기화 등 상대 경로를 사용하는 스크립트
- README 실행 명령과 개발 도구 설정

## 1. 공통 원칙

1. 상위 계층은 하위 계층을 사용할 수 있지만 하위 계층은 상위 계층을 import하지 않는다.
2. Back은 계층 경계를 유지하고 Front는 기능 단위 응집을 우선한다.
3. 의미와 변경 주기까지 같을 때만 공용 모듈로 승격한다.
4. 파일 길이는 분리 신호일 뿐 강제 기준이 아니다.
5. 구조 이동, 제품 용어 변경, API 변경은 같은 PR에 섞지 않는다.
6. 생성 코드, 빌드 산출물, 비밀값은 사람이 관리하는 소스와 분리한다.
7. 검증되지 않은 보안 가정을 확정된 사실처럼 문서에 쓰지 않는다.

## 2. 전체 저장소 구조

### API 저장소

```text
k-manner-speech-api/
├── app/
│   ├── main.py                  # 앱 조립과 라우터 등록
│   ├── core/                    # 설정, 인증, DB, 공통 예외
│   ├── routers/                 # HTTP 엔드포인트
│   ├── schemas/                 # Pydantic API 계약
│   ├── services/                # 유스케이스와 도메인 규칙
│   ├── models/                  # SQLAlchemy 영속성 모델
│   ├── repositories/            # 필요한 도메인만 사용하는 쿼리 경계
│   └── ai/                      # 프롬프트와 AI 공급자 구현
├── migrations/                  # Alembic 변경 이력
├── tests/
├── scripts/                     # OpenAPI 생성 등 자동화
├── docs/                        # ADR과 운영 문서
├── .github/workflows/
├── .env.example
├── alembic.ini
├── Dockerfile
├── pyproject.toml
├── uv.lock
└── README.md
```

### Front 저장소

```text
k-manner-speech-front/
├── scripts/                     # Figma 동기화 등 저장소 자동화
└── web/
    ├── public/
    ├── src/
    │   ├── main.tsx
    │   ├── index.css
    │   ├── app/                 # 라우터와 Provider 조립
    │   ├── features/            # 사용자 기능 단위 UI와 상태
    │   ├── components/          # 공용 UI와 앱 셸
    │   ├── api/                 # HTTP 클라이언트와 생성 타입
    │   ├── store/               # 기능에 속하지 않는 전역 상태
    │   ├── lib/                 # 도메인을 모르는 공용 코드
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

Front 내부 경로는 별도 언급이 없으면 `web/` 기준이다. 예를 들어 생성 타입 경로는 `web/src/api/generated/`다.

## 3. 백엔드 구조

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
│   ├── conversation/           # 대화 생성 유스케이스
│   └── feedback/               # 표현 평가 유스케이스
├── models/
│   ├── catalog.py
│   ├── user.py
│   └── chat/
│       ├── room.py
│       ├── message.py
│       └── feedback.py
├── repositories/              # 선택 사항
│   └── rooms.py               # 복잡·반복 쿼리가 있을 때만 추가
└── ai/
    ├── interfaces.py           # 공급자 교체를 위한 내부 계약
    ├── prompts/                # 버전 관리되는 프롬프트 자산
    └── providers/              # OpenAI, Gemini, ElevenLabs, demo 구현
```

`services/rooms/`만 하위 패키지인 이유는 방 생성·목록·메시지·피드백이 독립된 변경 이유를 갖기 때문이다. 파일이 하나뿐이라는 이유로 다른 서비스를 기계적으로 패키지화하지 않는다.

`web_speech.py`와 `speech.py`의 기존 이름 차이는 즉시 바꾸지 않는다. 이름 통일은 API·테스트·문서 영향을 확인한 동작 없는 별도 PR에서 수행한다.

### 책임과 의존 방향

| 계층 | 책임 | 포함하지 않는 것 |
| --- | --- | --- |
| `routers` | 경로, 인증 의존성, 입력 검증, HTTP 상태 코드 | SQL, 공급자 호출, 긴 비즈니스 로직 |
| `schemas` | 요청·응답 DTO와 검증 | DB 세션과 외부 API 호출 |
| `services` | 유스케이스, 소유권 검사, 트랜잭션 흐름 | FastAPI 라우트와 Response 조립 |
| `repositories` | 복잡·반복 SQLAlchemy 쿼리 | 사용자 정책과 비즈니스 판단 |
| `models` | 테이블, 관계, DB 제약 | 외부 API 응답 계약 |
| `ai` | 프롬프트, 인터페이스, 공급자 구현 | HTTP 라우팅과 사용자 권한 규칙 |
| `core` | 설정, 인증 검증, DB 연결, 공통 예외 | 특정 도메인 규칙 |

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

1. `services`와 `schemas`는 `routers`를 import하지 않는다.
2. Pydantic DTO와 SQLAlchemy 엔티티를 같은 클래스로 합치지 않는다.
3. 모든 사용자 소유 쿼리는 서비스 계층에서 검증된 사용자 ID로 필터링한다.
4. 단순 CRUD는 서비스가 세션을 직접 사용할 수 있다.
5. 복잡한 쿼리, 반복 조회, 교체 가능한 저장 경계가 필요할 때만 Repository를 도입한다.
6. 실제 AI 호출은 `ai/interfaces.py` 뒤에 두며 테스트에서는 결정적인 demo 구현으로 교체한다.
7. 도메인 간 조율은 상위 유스케이스 서비스가 담당하고 서로의 라우터를 호출하지 않는다.

### 네이밍

| 대상 | 규칙 | 예시 |
| --- | --- | --- |
| 파일·함수·변수 | `snake_case` | `get_room_by_id` |
| 클래스 | `PascalCase` | `RoomService` |
| 상수 | `UPPER_SNAKE_CASE` | `MAX_ROOM_SIZE` |
| 서비스 파일 | `services/`가 역할을 표현하므로 리소스명 사용 | `services/catalog.py` |
| API 경로 | `/api/v1` + 복수 리소스명 우선 | `/api/v1/rooms` |
| 테스트 | `test_<target>.py` | `test_room_service.py` |

## 4. 프론트엔드 구조

```text
web/src/
├── main.tsx
├── index.css
├── app/
│   ├── App.tsx                 # 화면과 전역 경계 조립
│   ├── router.tsx              # React Router 라우트 정의
│   ├── routeMeta.ts            # 제목·탭 등 라우트 메타데이터
│   └── providers/              # 인증, 테마, 데이터 Provider
├── features/
│   └── <feature>/
│       ├── components/
│       ├── hooks/
│       ├── api.ts
│       ├── store.ts
│       ├── types.ts
│       └── index.ts            # 다른 모듈에 허용하는 공개 API
├── components/
│   ├── ui/                     # 도메인을 모르는 기본 UI
│   └── shell/                  # 앱 프레임과 내비게이션
├── api/
│   ├── http.ts                 # Base URL, 인증 헤더, 공통 오류
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
5. 둘 이상의 기능에서 쓰이고 도메인을 몰라도 되는 UI만 `components/ui/`로 승격한다.
6. 재사용되더라도 도메인 의미가 있는 코드를 범용 `lib/`로 이동하지 않는다.
7. HTTP 요청은 공통 `api/http.ts`와 기능별 `features/<feature>/api.ts`를 통한다.
8. 간단한 UI 상태는 컴포넌트에 유지하고 복잡하거나 재사용되는 로직만 Hook으로 분리한다.
9. Supabase 클라이언트는 인증 세션에만 사용하고 서비스 테이블을 직접 조회하지 않는다.

| 상태 | 위치 |
| --- | --- |
| URL로 표현 가능한 상태 | 경로 파라미터 또는 search params |
| 단일 컴포넌트 UI 상태 | `useState`, `useReducer` |
| 한 Feature 트리에서 공유 | Feature Context, Hook 또는 Store |
| 서버 데이터 | API 계층과 서버 데이터 캐시 |
| 인증 세션 | 인증 Feature 또는 Supabase 세션 Provider |
| 여러 독립 화면의 상태 | 필요한 경우에만 전역 Store |

## 5. CORS·쿠키·CSRF

- 허용 Origin은 API 환경변수에 명시하고 로컬·스테이징·운영을 분리한다.
- 쿠키나 `credentials` 요청에서는 와일드카드 Origin을 사용하지 않는다.
- 쿠키의 `Secure`, `HttpOnly`, `SameSite`, `Domain` 정책을 환경별로 문서화한다.
- 상태 변경 요청에는 현재 인증 방식에 맞는 CSRF 방어를 적용한다.
- 브라우저에는 publishable/anon 키만 전달하며 서비스 역할 키와 DB 자격 증명은 절대 전달하지 않는다.

## 6. API 계약 관리

```text
Pydantic schema
    → 버전이 지정된 OpenAPI artifact
        → openapi-typescript
            → web/src/api/generated/
                → typecheck와 build
```

1. API CI가 OpenAPI JSON을 생성하고 API 커밋 SHA 또는 릴리스 버전을 기록한다.
2. Front는 고정된 artifact 버전에서 `web/src/api/generated/` 타입을 생성한다.
3. 생성 파일에는 직접 수정 금지 주석과 원본 버전을 기록한다.
4. Front CI는 재생성 결과와 커밋된 타입의 차이를 검사한다.
5. `oasdiff`의 경로·필드 삭제, 타입 변경, required 필드 추가 같은 breaking 변경은 기본 브랜치 CI를 실패시킨다.
6. 필드·선택적 엔드포인트 추가 같은 non-breaking 변경은 CI를 통과시키되 변경 요약을 PR에 경고로 남긴다.
7. breaking 변경은 새 API 버전 또는 사전 공지된 전환 기간, Front 전환 PR을 요구한다.

수동 `web/src/api/types.ts`는 OpenAPI 생성 자동화가 도입되기 전까지만 허용한다. `contract-check`가 기본 브랜치 CI에 추가되는 시점부터 새 수동 타입을 금지하고, 기존 수동 타입은 해당 스프린트 안에 생성 타입으로 교체한다.

두 저장소의 소스 경로를 상대 참조하거나 Git submodule로 결합하지 않는다.

## 7. 데이터베이스와 인증 보안

### 연결·권한 모델

| 자격 증명 | 사용 위치 | 규칙 |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy의 Postgres 직접 연결 | 서버 환경에만 보관, 코드 기본값 금지 |
| `SUPABASE_SERVICE_ROLE_KEY` | 서버가 Supabase API를 관리자 권한으로 호출할 때만 사용 | 서버 환경에만 보관, 브라우저 전달 금지 |
| publishable/anon key | 브라우저 Supabase Auth 세션 | 서비스 테이블 직접 접근 권한을 전제로 하지 않음 |

현재 구조는 요청별 사용자 JWT를 SQLAlchemy 세션에 전달하지 않는다. 따라서 서비스 계층의 소유권 검사가 FastAPI 경로의 실질적인 접근 통제다. 모든 사용자 소유 SELECT, UPDATE, DELETE는 검증된 사용자 ID로 필터링하고, 타인의 리소스는 존재 여부를 노출하지 않는 응답 정책을 사용한다.

RLS는 노출 스키마의 Data API에서 anon/authenticated 직접 접근을 제한한다. 관리자 권한 또는 RLS 우회 역할로 실행되는 서버 쿼리의 소유권 누락을 막는 장치로 가정하지 않는다. Supabase 서비스 역할은 RLS를 우회하므로 서버 전용으로 관리해야 한다. [Supabase RLS 문서](https://supabase.com/docs/guides/database/postgres/row-level-security)

### 마이그레이션과 Data API 권한

```text
k-manner-speech-api/
├── alembic.ini
├── app/models/
└── migrations/
    ├── env.py
    ├── README.md
    └── versions/
        └── <revision>_<change_name>.py
```

1. 운영 스키마 변경은 새 Alembic 리비전으로 남긴다.
2. 모델, 마이그레이션, RLS·GRANT·Data API 노출 정책은 같은 PR에서 검토한다.
3. 노출 스키마의 테이블에는 RLS를 활성화한다.
4. Front가 서비스 테이블을 직접 사용하지 않는다면 `anon`·`authenticated` 역할의 불필요한 테이블 권한을 회수하거나 Data API 노출을 제한한다.
5. 공유 또는 머지된 리비전을 수정하지 않고, 같은 변경을 별도 수동 SQL 파일과 중복 관리하지 않는다.

## 8. 테스트와 CI

```text
k-manner-speech-api/tests/
├── conftest.py
├── unit/
│   ├── services/
│   └── ai/
├── integration/
│   ├── routers/
│   └── database/
└── contract/
    └── test_openapi.py

k-manner-speech-front/web/
├── src/features/simulation/SimulationScreen.test.tsx
└── e2e/practice-flow.spec.ts
```

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

E2E와 단위 테스트는 준비 환경과 실패 원인이 다르므로 별도 CI 단계로 운영한다.

## 9. 환경변수

```text
k-manner-speech-api/.env.example
k-manner-speech-front/web/.env.example
```

- 실제 `.env`, `.env.local`은 커밋하지 않는다.
- 브라우저 번들에 포함되는 `VITE_*`에는 비밀값을 넣지 않는다.
- 새 변수는 예제 파일과 README에 함께 추가한다.
- API Base URL, 허용 Origin, 쿠키 정책은 환경별로 명시한다.
- CI 비밀값은 비밀 관리 도구나 저장소 비밀값 설정으로만 주입한다.

## 10. 적용 순서

1. 노출됐을 수 있는 DB·서비스 역할 자격 증명을 교체하고 소스 코드의 기본 비밀값을 제거한다.
2. 현재 파일과 목표 구조의 이동표를 작성한다.
3. 동작 변경 없이 파일·import만 정리하고 기존 테스트·빌드를 통과시킨다.
4. `app/ai/`, 선택적 Repository, OpenAPI 생성 자동화를 각각 독립 작업으로 도입한다.
5. API 소유권 통합 테스트, Data API 권한 검토, OpenAPI 계약 검사를 추가한다.
6. `web/` 평탄화는 필요성이 확정될 때만 0장의 체크리스트를 따르는 전용 PR에서 수행한다.
7. 제품 도메인 재명명과 API 경로 변경은 별도 ADR에서 호환 기간·deprecated 정책·Front 전환 계획을 확정한 뒤 진행한다.

## 11. 저장소별 소유권과 변경 판단

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
