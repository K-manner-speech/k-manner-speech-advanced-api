from __future__ import annotations

import json
from dataclasses import dataclass
from inspect import getsource
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.adapters.interview_provider import (
    InterviewAnalysisResult,
    InterviewProviderError,
    InterviewQuestionResult,
)
from worker.document_analysis import (
    DLQ_NAME,
    DocumentAnalysisWorker,
    QueueMessage,
    SqlDocumentAnalysisWorkerRepository,
    WorkItem,
)


class FakeEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1), 0.5] for index, _text in enumerate(texts)]


class FakeProvider:
    def analyze_document(self, _text: str) -> InterviewAnalysisResult:
        return InterviewAnalysisResult(
            sections={"summary": "분석", "skills": [], "experience": [], "risks": []},
            citations=[{"section": "summary", "evidence": "근거"}],
        )

    def generate_questions(
        self, _analysis: dict[str, Any], _conditions: dict[str, Any], question_count: int
    ) -> InterviewQuestionResult:
        return InterviewQuestionResult(
            questions=[
                {
                    "sequence": sequence,
                    "text": f"질문 {sequence}",
                    "type": "required",
                    "required": True,
                    "source_refs": [
                        {
                            "chunk_id": str(_analysis["evidence"][0]["chunk_id"]),
                            "section": "summary",
                        }
                    ],
                    "evaluation_focus": ["명확성"],
                }
                for sequence in range(1, question_count + 1)
            ]
        )


class FailingProvider(FakeProvider):
    def __init__(self, retryable: bool) -> None:
        self.retryable = retryable

    def analyze_document(self, _text: str) -> InterviewAnalysisResult:
        raise InterviewProviderError("PROVIDER_DOWN", retryable=self.retryable)


@dataclass
class FakeRepository:
    item: WorkItem
    completed: str | None = None
    retried: bool = False
    failed: bool = False
    failed_code: str | None = None
    acknowledged: bool = False
    rolled_back: bool = False

    def read_one(self) -> QueueMessage:
        return QueueMessage(message_id=10, job_id=self.item.job_id)

    def claim(self, _job_id: UUID) -> WorkItem:
        return self.item

    evidence: list[dict[str, Any]] | None = None
    persisted_chunk_count: int = 0

    def complete_analysis(
        self,
        _item: WorkItem,
        _result: InterviewAnalysisResult,
        chunks: list[object],
        embeddings: list[list[float]],
    ) -> bool:
        self.completed = "analysis"
        assert len(chunks) == len(embeddings)
        self.persisted_chunk_count = len(chunks)
        return True

    def retrieve_evidence(
        self, _item: WorkItem, _query_embedding: list[float], _threshold: float, _limit: int
    ) -> list[dict[str, Any]]:
        return self.evidence or []

    def complete_configuration(self, _item: WorkItem, _result: InterviewQuestionResult) -> bool:
        self.completed = "configuration"
        return True

    def retry(self, _item: WorkItem, _code: str) -> None:
        self.retried = True

    def fail(self, _item: WorkItem, _code: str) -> None:
        self.failed = True
        self.failed_code = _code

    def acknowledge(self, _message_id: int) -> None:
        self.acknowledged = True

    def rollback(self) -> None:
        self.rolled_back = True


def analysis_item(attempt_count: int = 1) -> WorkItem:
    return WorkItem(
        job_id=uuid4(),
        job_type="interview_document_analysis",
        target_id=uuid4(),
        processing_token=uuid4(),
        attempt_count=attempt_count,
        payload={"extracted_text": "문서 내용"},
    )


def configuration_item() -> WorkItem:
    return WorkItem(
        job_id=uuid4(),
        job_type="interview_configuration_generation",
        target_id=uuid4(),
        processing_token=uuid4(),
        attempt_count=1,
        payload={
            "retrieval_query": "신입 백엔드 기술 면접",
            "conditions": {},
            "question_count": 1,
        },
    )


def test_worker_completes_analysis_job_and_acknowledges() -> None:
    repository = FakeRepository(analysis_item())
    worker = DocumentAnalysisWorker(
        repository, FakeProvider(), FakeEmbeddingProvider(), maximum_attempts=3
    )

    assert worker.run_once() is True
    assert repository.completed == "analysis", "AC-T4-WORKER-LIFECYCLE"
    assert repository.persisted_chunk_count > 0
    assert repository.acknowledged is True


def test_worker_retries_then_fails_at_limit() -> None:
    retry_repository = FakeRepository(analysis_item(attempt_count=2))
    DocumentAnalysisWorker(
        retry_repository,
        FailingProvider(retryable=True),
        FakeEmbeddingProvider(),
        maximum_attempts=3,
    ).run_once()
    assert retry_repository.retried is True
    assert retry_repository.acknowledged is True

    failed_repository = FakeRepository(analysis_item(attempt_count=3))
    DocumentAnalysisWorker(
        failed_repository,
        FailingProvider(retryable=True),
        FakeEmbeddingProvider(),
        maximum_attempts=3,
    ).run_once()
    assert failed_repository.failed is True
    assert failed_repository.retried is False
    assert failed_repository.acknowledged is True


def test_worker_does_not_acknowledge_lost_claim() -> None:
    repository = FakeRepository(analysis_item())
    repository.complete_analysis = (  # type: ignore[method-assign]
        lambda _item, _result, _chunks, _embeddings: False
    )

    worker = DocumentAnalysisWorker(repository, FakeProvider(), FakeEmbeddingProvider(), 3)

    assert worker.run_once() is False
    assert repository.acknowledged is False


def test_worker_isolates_unexpected_job_exception() -> None:
    repository = FakeRepository(analysis_item())
    repository.complete_analysis = (  # type: ignore[method-assign]
        lambda _item, _result, _chunks, _embeddings: (_ for _ in ()).throw(
            RuntimeError("unexpected")
        )
    )

    try:
        completed = DocumentAnalysisWorker(
            repository, FakeProvider(), FakeEmbeddingProvider(), 3
        ).run_once()
    except RuntimeError:
        pytest.fail("AC-T4-UNEXPECTED-ISOLATED")

    assert completed is True
    assert repository.rolled_back is True, "AC-T4-UNEXPECTED-ISOLATED"
    assert repository.failed is True
    assert repository.failed_code == "UNEXPECTED_DOCUMENT_JOB_ERROR"
    assert repository.acknowledged is True


def test_configuration_retrieves_evidence_before_question_generation() -> None:
    item = configuration_item()
    chunk_id = uuid4()
    repository = FakeRepository(
        item, evidence=[{"chunk_id": chunk_id, "content": "FastAPI API 개발"}]
    )

    worker = DocumentAnalysisWorker(
        repository,
        FakeProvider(),
        FakeEmbeddingProvider(),
        maximum_attempts=3,
        similarity_threshold=0.7,
        retrieval_limit=8,
    )

    assert worker.run_once() is True
    assert repository.completed == "configuration"


def test_configuration_fails_without_retrieved_evidence() -> None:
    repository = FakeRepository(configuration_item())
    worker = DocumentAnalysisWorker(
        repository, FakeProvider(), FakeEmbeddingProvider(), maximum_attempts=3
    )

    assert worker.run_once() is True
    assert repository.failed is True
    assert repository.completed is None


def test_sql_worker_preserves_success_status_and_document_dlq() -> None:
    source = getsource(SqlDocumentAnalysisWorkerRepository._succeed_job)

    assert '"status": JobStatus.SUCCEEDED.value' in source, "AC-T4-WORKER-LIFECYCLE"
    assert DLQ_NAME == "document_analysis_dlq", "AC-T4-WORKER-LIFECYCLE"


def test_sql_worker_uses_deployed_document_chunks_contract() -> None:
    persistence = getsource(SqlDocumentAnalysisWorkerRepository.complete_analysis)
    retrieval = getsource(SqlDocumentAnalysisWorkerRepository.retrieve_evidence)

    assert "public.document_chunks" in persistence
    assert "public.document_chunks" in retrieval
    assert "public.interview_document_chunks" not in persistence + retrieval
    assert "join public.interview_documents d" in persistence
    assert "d.version_no as document_version" in persistence
    for required_column in ("document_version", "section", "source_ref"):
        assert required_column in persistence


class ConfigurationPersistenceResult:
    def first(self) -> tuple[int]:
        return (1,)


class ConfigurationPersistenceSession:
    def __init__(self) -> None:
        self.parameters: list[dict[str, object]] = []
        self.committed = False

    def execute(
        self, _statement: object, parameters: dict[str, object]
    ) -> ConfigurationPersistenceResult:
        self.parameters.append(parameters)
        return ConfigurationPersistenceResult()

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass


def test_complete_configuration_serializes_source_ref_uuid_as_json_string() -> None:
    session = ConfigurationPersistenceSession()
    repository = SqlDocumentAnalysisWorkerRepository(Session(bind=None))
    repository._session = session  # type: ignore[assignment]
    chunk_id = uuid4()
    result = InterviewQuestionResult(
        questions=[
            {
                "sequence": 1,
                "text": "JWT 경험을 설명해 주세요.",
                "type": "required",
                "required": True,
                "source_refs": [{"chunk_id": chunk_id, "section": "document"}],
                "evaluation_focus": ["구체성"],
            }
        ]
    )

    assert repository.complete_configuration(configuration_item(), result) is True

    source_refs = next(
        parameter["source_refs"]
        for parameter in session.parameters
        if "source_refs" in parameter
    )
    assert json.loads(str(source_refs)) == [
        {"chunk_id": str(chunk_id), "section": "document"}
    ]
    assert session.committed is True
