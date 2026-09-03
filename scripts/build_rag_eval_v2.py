# ruff: noqa: E501
"""개인정보 없는 한국어 개발자 이력서 21개와 RAG gold 189건을 생성한다."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Project:
    title: str
    query: str
    action: str
    result: str


@dataclass(frozen=True, slots=True)
class Profile:
    key: str
    name: str
    role: str
    skills: str
    projects: tuple[Project, Project, Project]
    hard_negatives: tuple[str, str]
    partial_extension: str


PROFILES = (
    Profile("java_backend", "김도윤", "백엔드 개발자", "Java, Spring Boot, JPA, PostgreSQL, Redis, k6", (
        Project("주문 조회 최적화", "JPA 조회 성능을 개선한 경험", "Hibernate 로그로 N+1을 재현하고 Fetch Join과 조회 전용 DTO를 적용했습니다.", "요청당 SQL을 101회에서 3회로, p95를 1.8초에서 420ms로 줄였습니다."),
        Project("재고 동시성 제어", "재고 동시성 문제를 해결한 경험", "낙관적 락과 비관적 락의 충돌률을 비교하고 낙관적 락 재시도를 두 번으로 제한했습니다.", "50개 동시 요청에서 성공 30건과 실패 20건으로 재고 정합성을 검증했습니다."),
        Project("결제 멱등성", "중복 결제를 방지한 경험", "Idempotency-Key와 요청 본문 해시를 저장하고 동일 키의 다른 본문은 409로 차단했습니다.", "장애 복구 후 중복 승인 0건을 통합 테스트로 확인했습니다.")),
        ("Kafka 컨슈머 리밸런싱 장애를 해결한 경험", "Redis Redlock으로 다중 리전 락을 구현한 경험"), "Kafka 이벤트 발행까지 원자적으로 처리했습니다"),
    Profile("python_ai", "이서현", "AI 서비스 백엔드 개발자", "Python, FastAPI, Pydantic, PostgreSQL, PGMQ, OpenAI API", (
        Project("비동기 AI 작업", "AI 작업을 비동기로 처리한 경험", "queued, processing, succeeded, failed 상태와 visibility timeout을 정의했습니다.", "중단된 작업을 만료 후 재처리하고 최종 실패는 DLQ로 격리했습니다."),
        Project("Structured Output 검증", "생성형 AI JSON을 검증한 경험", "Pydantic 스키마와 카테고리 중복·누락 도메인 검증을 이중으로 적용했습니다.", "형식 오류 재시도를 한 번으로 제한하고 계약 테스트를 작성했습니다."),
        Project("피드백 시간 초과", "AI 응답 시간 초과를 개선한 경험", "모델 응답과 DB 저장 시간을 분리 측정하고 출력 스키마와 토큰 한도를 줄였습니다.", "중복 생성 작업을 차단하고 실패 원인을 화면에 구분해 표시했습니다.")),
        ("Redis 분산 락으로 재고를 제어한 경험", "GPU 모델 서빙을 Kubernetes에서 오토스케일링한 경험"), "JSON Schema를 클라이언트에도 자동 배포했습니다"),
    Profile("frontend", "박지훈", "프론트엔드 개발자", "TypeScript, React, TanStack Query, Vite, Playwright", (
        Project("비동기 결과 화면", "비동기 작업 화면 상태를 설계한 경험", "processing, succeeded, failed 상태별 화면과 오류별 재시도 동선을 분리했습니다.", "사용자가 빈 화면에서 이탈하는 비율을 23%에서 8%로 줄였습니다."),
        Project("캐시 키 정리", "프론트엔드 캐시 충돌을 해결한 경험", "queryKey를 사용자와 방 ID 단위로 분리하고 mutation 성공 후 관련 캐시만 무효화했습니다.", "다른 면접 결과가 섞이는 재현 테스트를 통과했습니다."),
        Project("음성 스트리밍", "음성 첫 재생 시간을 개선한 경험", "첫 PCM 청크를 받는 즉시 AudioContext로 재생하고 페이지 이동 시 요청을 취소했습니다.", "첫 재생 시간을 4.2초에서 1.6초로 줄였습니다.")),
        ("JPA Fetch Join으로 N+1을 해결한 경험", "React Native로 오프라인 동기화를 구현한 경험"), "WebRTC 기반 양방향 음성 통화를 구현했습니다"),
    Profile("rag", "최유진", "RAG 엔지니어", "Python, OpenAI Embeddings, pgvector, PostgreSQL FTS, RRF, RAGAS", (
        Project("하이브리드 검색", "벡터와 키워드 검색을 결합한 경험", "pgvector와 Full Text Search 결과를 Reciprocal Rank Fusion으로 결합했습니다.", "120개 질의의 Recall@5를 78%에서 89%로 높였습니다."),
        Project("구조 기반 청킹", "RAG 청킹을 개선한 경험", "제목과 문단 경계를 우선하고 tokenizer 기준 15% overlap을 적용했습니다.", "정답 근거가 한 청크에 포함되는 비율을 71%에서 92%로 높였습니다."),
        Project("근거 검증", "RAG 인용 근거를 검증한 경험", "모델 citation의 chunk_id가 검색 결과에 실제 존재하는지 서버에서 검사했습니다.", "검색 근거 밖의 지시를 따르는 비율을 18%에서 0%로 낮췄습니다.")),
        ("Kubernetes 카나리 배포를 자동화한 경험", "그래프 RAG로 다중 홉 검색을 구현한 경험"), "ColBERT reranker를 적용해 재정렬했습니다"),
    Profile("platform", "정하늘", "플랫폼 엔지니어", "Go, Kubernetes, Helm, Argo CD, Prometheus, Terraform", (
        Project("무중단 배포", "Kubernetes 무중단 배포를 개선한 경험", "startup과 readiness probe를 분리하고 preStop과 종료 유예 시간을 조정했습니다.", "종료 중 요청 오류율을 3.1%에서 0.2%로 낮췄습니다."),
        Project("통합 관측성", "로그 메트릭 트레이스를 연결한 경험", "Prometheus, Loki, Tempo를 trace_id로 연결해 Grafana 탐색 동선을 구성했습니다.", "평균 원인 식별 시간을 32분에서 11분으로 줄였습니다."),
        Project("Terraform 모듈화", "인프라 변경을 코드로 관리한 경험", "VPC와 EKS 모듈을 분리하고 plan 결과를 PR에 자동 첨부했습니다.", "수동 설정 차이를 제거하고 공개 보안 그룹을 정적 분석으로 차단했습니다.")),
        ("생성형 AI structured output을 검증한 경험", "서비스 메시 Istio mTLS를 구축한 경험"), "Argo Rollouts 카나리 분석을 자동화했습니다"),
    Profile("data", "윤서준", "데이터 엔지니어", "Python, Airflow, Spark, Kafka, BigQuery, dbt", (
        Project("배치 파이프라인", "데이터 배치 파이프라인을 안정화한 경험", "Airflow 태스크를 날짜 파티션 기준으로 멱등하게 만들고 실패 구간만 재실행했습니다.", "전체 재처리 시간을 4시간에서 38분으로 줄였습니다."),
        Project("Spark 비용 최적화", "Spark 작업 성능을 개선한 경험", "skew key를 분리하고 broadcast join 임계값과 파티션 수를 실험했습니다.", "셔플 데이터를 1.2TB에서 310GB로 줄였습니다."),
        Project("데이터 품질", "데이터 품질 검증을 자동화한 경험", "dbt test로 null, unique, referential integrity 규칙을 배포 차단 조건에 연결했습니다.", "잘못된 집계가 대시보드에 반영되는 사고를 월 6건에서 0건으로 줄였습니다.")),
        ("Flink 실시간 CEP를 구현한 경험", "Kafka exactly-once 트랜잭션을 적용한 경험"), "머신러닝 피처 드리프트까지 자동 탐지했습니다"),
    Profile("android", "한지민", "Android 개발자", "Kotlin, Jetpack Compose, Room, Retrofit, Coroutines", (
        Project("오프라인 동기화", "모바일 오프라인 동기화를 구현한 경험", "Room outbox에 변경을 저장하고 네트워크 복구 시 순서대로 동기화했습니다.", "중복 전송과 유실 시나리오 42개를 계측 테스트로 검증했습니다."),
        Project("화면 성능", "Android 화면 렌더링 성능을 개선한 경험", "Compose recomposition 횟수와 이미지 디코딩 시간을 측정해 상태 범위를 줄였습니다.", "스크롤 jank 비율을 14%에서 3%로 낮췄습니다."),
        Project("앱 보안", "모바일 토큰 보안을 개선한 경험", "access token을 EncryptedSharedPreferences에 저장하고 인증 실패 시 단일 갱신 mutex를 적용했습니다.", "동시 401 응답에서도 refresh 요청이 한 번만 발생하도록 검증했습니다.")),
        ("iOS SwiftUI 앱을 개발한 경험", "WebRTC SFU를 직접 구축한 경험"), "생체 인증 실패 시 서버 키를 폐기했습니다"),
    Profile("ios", "서예린", "iOS 개발자", "Swift, SwiftUI, Combine, CoreData, XCTest", (
        Project("상태 관리", "SwiftUI 화면 상태를 안정화한 경험", "단방향 상태 흐름으로 로딩과 오류 상태를 분리하고 중복 Task를 취소했습니다.", "화면 재진입 시 중복 API 호출을 7회에서 1회로 줄였습니다."),
        Project("로컬 데이터", "iOS 오프라인 데이터를 동기화한 경험", "CoreData 변경 이력과 서버 revision을 비교해 충돌 정책을 적용했습니다.", "비행기 모드 전환을 포함한 UI 테스트를 자동화했습니다."),
        Project("접근성", "iOS 접근성을 개선한 경험", "VoiceOver 순서와 Dynamic Type에서 잘리는 화면을 snapshot test로 검사했습니다.", "접근성 감사에서 주요 오류 18건을 2건으로 줄였습니다.")),
        ("Android WorkManager 동기화를 구현한 경험", "Metal 셰이더로 영상 필터를 개발한 경험"), "CloudKit 다중 기기 병합까지 구현했습니다"),
    Profile("security", "오민재", "보안 엔지니어", "Python, WAF, SIEM, OAuth2, OIDC, Burp Suite", (
        Project("권한 검증", "리소스 소유권 검증을 개선한 경험", "요청 본문 user_id를 신뢰하지 않고 토큰 subject와 DB 소유권 조건을 결합했습니다.", "수평 권한 상승 테스트 36건을 모두 차단했습니다."),
        Project("탐지 규칙", "보안 로그 탐지를 개선한 경험", "인증 실패와 IP, device fingerprint를 시간 창으로 집계하는 SIEM 규칙을 만들었습니다.", "계정 탈취 탐지 평균 시간을 28분에서 4분으로 줄였습니다."),
        Project("비밀 관리", "애플리케이션 비밀 관리를 개선한 경험", "정적 키를 Secret Manager 참조로 교체하고 CI 로그 마스킹을 적용했습니다.", "저장소 secret scanning 경고를 배포 차단 조건으로 설정했습니다.")),
        ("블록체인 스마트 컨트랙트를 감사한 경험", "제로 트러스트 서비스 메시를 구축한 경험"), "하드웨어 HSM 키 순환까지 자동화했습니다"),
    Profile("devops", "노하준", "DevOps 엔지니어", "GitHub Actions, Docker, Kubernetes, Argo CD, Bash", (
        Project("CI 가속", "CI 빌드 시간을 줄인 경험", "변경 경로별 작업 분리와 Docker layer cache, 테스트 shard를 적용했습니다.", "PR 검증 시간을 24분에서 8분으로 줄였습니다."),
        Project("GitOps 배포", "GitOps 배포를 구축한 경험", "환경별 Helm values와 Argo CD sync wave로 마이그레이션 순서를 제어했습니다.", "수동 배포 작업을 제거하고 변경 이력을 PR로 남겼습니다."),
        Project("장애 복구", "배포 장애 복구를 자동화한 경험", "헬스 지표 임계값 초과 시 이전 이미지 digest로 롤백하는 작업을 구성했습니다.", "평균 복구 시간을 21분에서 7분으로 줄였습니다.")),
        ("Jenkins shared library를 개발한 경험", "AWS 멀티 리전 active-active를 구축한 경험"), "Chaos Mesh로 리전 장애까지 검증했습니다"),
    Profile("mlops", "문채원", "MLOps 엔지니어", "Python, MLflow, Kubernetes, KServe, Evidently, S3", (
        Project("모델 배포", "머신러닝 모델 배포를 자동화한 경험", "MLflow model version과 이미지 digest를 연결하고 KServe canary 비율을 단계적으로 높였습니다.", "배포 승인과 롤백 시간을 40분에서 9분으로 줄였습니다."),
        Project("드리프트 감지", "모델 데이터 드리프트를 감지한 경험", "학습 데이터와 운영 입력의 PSI와 feature 분포를 매일 비교했습니다.", "임계값 초과 시 재학습 후보를 생성하고 담당자 승인 후 실행했습니다."),
        Project("추론 비용", "모델 추론 비용을 최적화한 경험", "동적 배치와 GPU utilization을 측정해 요청량별 replica 정책을 조정했습니다.", "동일 p95를 유지하며 GPU 시간을 31% 줄였습니다.")),
        ("LLM LoRA 파인튜닝을 수행한 경험", "Kubeflow Pipelines를 구축한 경험"), "온라인 A/B 실험의 통계적 유의성까지 판정했습니다"),
    Profile("qa", "송지아", "QA 자동화 엔지니어", "Playwright, Pytest, Appium, k6, Allure", (
        Project("E2E 안정화", "불안정한 E2E 테스트를 개선한 경험", "고정 sleep을 제거하고 네트워크 응답과 UI 상태를 명시적으로 기다렸습니다.", "flaky 비율을 17%에서 1.8%로 줄였습니다."),
        Project("계약 테스트", "API 계약 테스트를 구축한 경험", "OpenAPI schema와 실제 응답의 필수 필드 및 nullable 변경을 CI에서 검사했습니다.", "프론트 통합 단계의 계약 오류를 월 9건에서 1건으로 줄였습니다."),
        Project("부하 테스트", "서비스 부하 테스트를 수행한 경험", "k6로 단계별 사용자 증가와 spike 시나리오를 분리하고 p95와 오류율 기준을 설정했습니다.", "DB pool 병목을 찾아 최대 안정 처리량을 2.1배 높였습니다.")),
        ("Selenium Grid를 Kubernetes에 구축한 경험", "침투 테스트로 SQL injection을 발견한 경험"), "모바일 실기기 팜까지 운영했습니다"),
    Profile("cloud", "배준호", "클라우드 엔지니어", "AWS, Terraform, EKS, RDS, CloudFront, FinOps", (
        Project("네트워크 분리", "클라우드 네트워크를 설계한 경험", "public, private, data subnet을 분리하고 VPC endpoint로 외부 NAT 경로를 줄였습니다.", "데이터베이스 공개 접근을 제거하고 NAT 비용을 18% 줄였습니다."),
        Project("RDS 복구", "데이터베이스 복구 절차를 검증한 경험", "PITR 복구와 애플리케이션 연결 전환을 격리 환경에서 분기마다 연습했습니다.", "복구 목표 시간을 60분에서 22분으로 줄였습니다."),
        Project("비용 최적화", "클라우드 비용을 최적화한 경험", "태그와 CUR 데이터를 연결해 유휴 인스턴스와 과다 예약 자원을 탐지했습니다.", "월 인프라 비용을 24% 줄이고 서비스별 예산 알림을 설정했습니다.")),
        ("GCP BigQuery 비용을 최적화한 경험", "AWS Outposts 하이브리드 구성을 구축한 경험"), "멀티 리전 active-active 장애 조치까지 구현했습니다"),
    Profile("database", "강수빈", "DBA", "PostgreSQL, MySQL, pgBackRest, Patroni, Prometheus", (
        Project("슬로 쿼리", "데이터베이스 슬로 쿼리를 개선한 경험", "실행 계획과 buffer hit를 비교해 복합 인덱스 순서와 통계 정보를 조정했습니다.", "p95 쿼리 시간을 2.4초에서 180ms로 줄였습니다."),
        Project("고가용성", "PostgreSQL 고가용성을 운영한 경험", "Patroni leader election과 replication lag 임계값을 장애 훈련으로 검증했습니다.", "계획된 failover의 쓰기 중단 시간을 45초에서 12초로 줄였습니다."),
        Project("백업 복구", "데이터베이스 백업 복구를 검증한 경험", "pgBackRest 증분 백업을 별도 계정에 저장하고 월별 전체 복구를 자동화했습니다.", "복구 성공 여부와 RPO를 대시보드에 기록했습니다.")),
        ("Oracle RAC를 운영한 경험", "MongoDB sharding을 재설계한 경험"), "논리 복제로 무중단 메이저 업그레이드까지 수행했습니다"),
    Profile("game_server", "임태현", "게임 서버 개발자", "C++, C#, Redis, PostgreSQL, gRPC, Unity", (
        Project("매칭 서버", "게임 매칭 지연을 개선한 경험", "등급 범위를 시간에 따라 넓히는 큐와 지역별 latency 조건을 구현했습니다.", "평균 매칭 시간을 48초에서 19초로 줄였습니다."),
        Project("세션 복구", "게임 세션 연결 복구를 구현한 경험", "재접속 token과 마지막 처리 sequence를 검증해 중복 명령을 무시했습니다.", "모바일 네트워크 전환 시 세션 복구 성공률을 93%로 높였습니다."),
        Project("리더보드", "대규모 리더보드를 구현한 경험", "Redis sorted set과 시즌별 snapshot을 분리하고 상위권 갱신을 비동기로 저장했습니다.", "100만 사용자 조건에서 조회 p95 35ms를 유지했습니다.")),
        ("Unreal Engine 렌더링을 최적화한 경험", "WebRTC 음성 채팅 SFU를 구축한 경험"), "치트 탐지 머신러닝 모델까지 배포했습니다"),
    Profile("embedded", "조아라", "임베디드 개발자", "C, C++, FreeRTOS, CAN, UART, Python", (
        Project("센서 수집", "실시간 센서 수집 안정성을 개선한 경험", "ISR에서는 ring buffer에만 기록하고 파싱과 전송을 별도 task로 분리했습니다.", "1kHz 입력에서 데이터 유실률을 2.3%에서 0.01%로 낮췄습니다."),
        Project("OTA 업데이트", "펌웨어 OTA 복구를 구현한 경험", "A/B 파티션과 서명 검증, 부팅 성공 marker를 사용해 실패 시 이전 이미지로 복귀했습니다.", "전원 차단 50개 시점의 복구 테스트를 통과했습니다."),
        Project("CAN 진단", "CAN 통신 장애를 분석한 경험", "bus-off와 error frame을 타임스탬프로 수집해 특정 ECU의 재전송 폭증을 찾았습니다.", "재현 장비에서 장애 시간을 6시간에서 40분으로 줄였습니다.")),
        ("Linux 커널 드라이버를 개발한 경험", "FPGA Verilog 파이프라인을 구현한 경험"), "ASIL-D 기능 안전 인증까지 수행했습니다"),
    Profile("product_backend", "이현우", "프로덕트 백엔드 개발자", "Node.js, NestJS, PostgreSQL, Redis, Kafka", (
        Project("알림 발송", "대규모 알림 발송을 안정화한 경험", "outbox와 Kafka consumer idempotency key로 DB 변경과 발송 이벤트를 연결했습니다.", "중복 발송률을 0.8%에서 0.01%로 줄였습니다."),
        Project("검색 API", "상품 검색 API 성능을 개선한 경험", "필터 조합별 실행 계획을 분석하고 cursor pagination과 부분 인덱스를 적용했습니다.", "p95 응답을 780ms에서 190ms로 줄였습니다."),
        Project("권한 모델", "조직 단위 권한 모델을 설계한 경험", "사용자-조직-역할 관계와 리소스 scope를 DB 조회 조건에 포함했습니다.", "다른 조직 데이터 접근을 막는 통합 테스트 28건을 작성했습니다.")),
        ("Elasticsearch 벡터 검색을 구현한 경험", "GraphQL federation을 운영한 경험"), "이벤트 소싱으로 모든 상태를 재구성했습니다"),
    Profile("sre", "김나연", "SRE", "Go, Kubernetes, Prometheus, Grafana, OpenTelemetry, PagerDuty", (
        Project("SLO 운영", "서비스 SLO를 설계한 경험", "성공률과 지연시간 SLI를 사용자 여정별로 정의하고 error budget 정책을 배포 승인에 연결했습니다.", "무의미한 경고를 46% 줄이고 사용자 영향 장애 탐지를 앞당겼습니다."),
        Project("장애 대응", "장애 대응 절차를 개선한 경험", "incident commander와 communication 역할을 분리하고 타임라인 기록 bot을 만들었습니다.", "평균 완화 시간을 37분에서 16분으로 줄였습니다."),
        Project("용량 계획", "서비스 용량 계획을 수행한 경험", "요청량과 CPU, queue wait의 상관관계를 모델링하고 분기별 headroom을 계산했습니다.", "트래픽 행사에서 오류율 0.1% 이하를 유지했습니다.")),
        ("eBPF 커널 프로파일러를 개발한 경험", "멀티 클라우드 service mesh를 구축한 경험"), "완전 자동 장애 복구로 운영자 호출을 제거했습니다"),
    Profile("blockchain", "백승민", "블록체인 백엔드 개발자", "Solidity, Ethereum, Node.js, PostgreSQL, The Graph", (
        Project("이벤트 인덱싱", "블록체인 이벤트 인덱서를 구현한 경험", "block number와 log index를 유일 키로 저장하고 reorg 발생 시 확정 전 블록을 되돌렸습니다.", "중복 이벤트 없이 200만 로그를 재처리했습니다."),
        Project("지갑 보안", "지갑 서명 검증을 구현한 경험", "nonce와 domain separator를 포함한 EIP-712 서명을 서버에서 검증했습니다.", "재사용 서명과 다른 체인의 replay 공격 테스트를 차단했습니다."),
        Project("가스 최적화", "스마트 컨트랙트 가스 비용을 줄인 경험", "storage packing과 calldata 사용 전후를 Foundry gas report로 비교했습니다.", "주요 거래의 평균 가스를 21% 줄였습니다.")),
        ("Hyperledger Fabric 네트워크를 운영한 경험", "영지식 증명 회로를 개발한 경험"), "정형 검증으로 컨트랙트 무결성을 증명했습니다"),
    Profile("search", "유다은", "검색 엔지니어", "Elasticsearch, OpenSearch, Java, Kafka, Python", (
        Project("한국어 검색", "한국어 검색 품질을 개선한 경험", "형태소 분석기와 동의어 사전을 질의 유형별로 비교하고 nDCG 평가셋을 만들었습니다.", "상위 10개 결과의 nDCG를 0.71에서 0.82로 높였습니다."),
        Project("색인 무중단 전환", "검색 색인을 무중단으로 교체한 경험", "새 인덱스에 dual write한 뒤 문서 수와 checksum을 비교하고 alias를 원자적으로 전환했습니다.", "서비스 중단 없이 4억 문서를 재색인했습니다."),
        Project("개인화 랭킹", "검색 랭킹을 개인화한 경험", "기본 BM25 점수에 최근 클릭 카테고리와 품절 패널티를 feature로 결합했습니다.", "온라인 실험에서 검색 전환율을 6.4% 높였습니다.")),
        ("pgvector RAG 검색을 구현한 경험", "이미지 CLIP 멀티모달 검색을 구현한 경험"), "LLM reranker로 모든 질의를 재정렬했습니다"),
    Profile("network", "전시우", "네트워크 엔지니어", "BGP, OSPF, Cisco, Juniper, Wireshark, Ansible", (
        Project("BGP 장애", "BGP 라우팅 장애를 분석한 경험", "route flap과 prefix 변경을 타임라인으로 비교해 잘못된 export policy를 찾았습니다.", "우회 경로 수렴 시간을 90초에서 18초로 줄였습니다."),
        Project("설정 자동화", "네트워크 설정을 자동화한 경험", "Ansible template과 사전 diff, 승인 단계를 사용해 장비 설정을 배포했습니다.", "수동 설정 오류를 분기 7건에서 1건으로 줄였습니다."),
        Project("트래픽 분석", "네트워크 지연 원인을 분석한 경험", "NetFlow와 packet capture를 연결해 특정 백업 트래픽의 queue 점유를 확인했습니다.", "업무 시간대 패킷 손실을 2.8%에서 0.1%로 낮췄습니다.")),
        ("Kubernetes CNI 플러그인을 개발한 경험", "5G 코어 네트워크를 구축한 경험"), "SD-WAN 회선 비용 최적화까지 자동화했습니다"),
)


def resume_text(profile: Profile) -> str:
    parts = [f"{profile.name} | {profile.role}", "기술", profile.skills, "프로젝트 경험"]
    for project in profile.projects:
        parts.extend(
            [
                project.title,
                project.action,
                project.result,
                f"문제를 추측으로 수정하지 않고 재현 조건과 관측 지표를 먼저 정의했습니다. {project.title}에서 선택하지 않은 대안과 트레이드오프를 기록하고 동료 리뷰를 받았습니다.",
                f"정상 경로뿐 아니라 중복 요청, 지연, 재시작, 경계값을 테스트했습니다. {project.title} 변경 후에는 동일 입력으로 회귀 테스트하고 배포 지표가 기준을 벗어나면 롤백하도록 준비했습니다.",
            ]
        )
    return "\n\n".join(parts)


def cases(profile: Profile) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    number = 1
    for project in profile.projects:
        for query, quote in ((project.query, project.action), (f"{project.title} 결과를 수치로 검증한 경험", project.result)):
            records.append(
                {
                    "case_id": f"{profile.key}-{number:02d}",
                    "document_id": profile.key,
                    "desired_role": profile.role,
                    "query": query,
                    "relevant_evidence": [{"section": project.title, "quote": quote, "relevance": 2}],
                    "expected_behavior": "retrieve_evidence",
                }
            )
            number += 1
    for query in profile.hard_negatives:
        records.append(
            {
                "case_id": f"{profile.key}-{number:02d}",
                "document_id": profile.key,
                "desired_role": profile.role,
                "query": query,
                "relevant_evidence": [],
                "expected_behavior": "insufficient_evidence",
                "negative_type": "hard_negative",
            }
        )
        number += 1
    base = profile.projects[0]
    records.append(
        {
            "case_id": f"{profile.key}-{number:02d}",
            "document_id": profile.key,
            "desired_role": profile.role,
            "query": f"{base.query}이 있으며 추가로 {profile.partial_extension}",
            "relevant_evidence": [{"section": base.title, "quote": base.action, "relevance": 1}],
            "expected_behavior": "partial_evidence",
            "unsupported_requirement": profile.partial_extension,
        }
    )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    for profile in PROFILES:
        text = resume_text(profile)
        filename = f"{profile.key}.txt"
        (args.output_dir / filename).write_text(text, encoding="utf-8")
        manifest.append(
            {
                "document_id": profile.key,
                "text": filename,
                "role": profile.role,
                "word_count": len(text.split()),
                "synthetic": True,
            }
        )
        records.extend(cases(profile))
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "rag_gold_dataset.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {
        "documents": len(PROFILES),
        "cases": len(records),
        "retrieve_evidence": sum(item["expected_behavior"] == "retrieve_evidence" for item in records),
        "insufficient_evidence": sum(item["expected_behavior"] == "insufficient_evidence" for item in records),
        "partial_evidence": sum(item["expected_behavior"] == "partial_evidence" for item in records),
    }
    (args.output_dir / "README.md").write_text(
        "# Korean Resume RAG Eval v2\n\n"
        "개인정보 없는 합성 이력서 21개와 직접 근거, hard negative, partial evidence 사례입니다.\n\n"
        f"```json\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n```\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
