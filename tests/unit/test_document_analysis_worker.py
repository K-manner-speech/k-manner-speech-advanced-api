from __future__ import annotations

from dataclasses import dataclass
from inspect import getsource
from typing import Any
from uuid import UUID, uuid4

import pytest

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
                    "source_refs": [{"section": "summary"}],
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

    def complete_analysis(self, _item: WorkItem, _result: InterviewAnalysisResult) -> bool:
        self.completed = "analysis"
        return True

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


def test_worker_completes_analysis_job_and_acknowledges() -> None:
    repository = FakeRepository(analysis_item())
    worker = DocumentAnalysisWorker(repository, FakeProvider(), maximum_attempts=3)

    assert worker.run_once() is True
    assert repository.completed == "analysis", "AC-T4-WORKER-LIFECYCLE"
    assert repository.acknowledged is True


def test_worker_retries_then_fails_at_limit() -> None:
    retry_repository = FakeRepository(analysis_item(attempt_count=2))
    DocumentAnalysisWorker(
        retry_repository, FailingProvider(retryable=True), maximum_attempts=3
    ).run_once()
    assert retry_repository.retried is True
    assert retry_repository.acknowledged is True

    failed_repository = FakeRepository(analysis_item(attempt_count=3))
    DocumentAnalysisWorker(
        failed_repository, FailingProvider(retryable=True), maximum_attempts=3
    ).run_once()
    assert failed_repository.failed is True
    assert failed_repository.retried is False
    assert failed_repository.acknowledged is True


def test_worker_does_not_acknowledge_lost_claim() -> None:
    repository = FakeRepository(analysis_item())
    repository.complete_analysis = lambda _item, _result: False  # type: ignore[method-assign]

    assert DocumentAnalysisWorker(repository, FakeProvider(), 3).run_once() is False
    assert repository.acknowledged is False


def test_worker_isolates_unexpected_job_exception() -> None:
    repository = FakeRepository(analysis_item())
    repository.complete_analysis = lambda _item, _result: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("unexpected")
    )

    try:
        completed = DocumentAnalysisWorker(repository, FakeProvider(), 3).run_once()
    except RuntimeError:
        pytest.fail("AC-T4-UNEXPECTED-ISOLATED")

    assert completed is True
    assert repository.rolled_back is True, "AC-T4-UNEXPECTED-ISOLATED"
    assert repository.failed is True
    assert repository.failed_code == "UNEXPECTED_DOCUMENT_JOB_ERROR"
    assert repository.acknowledged is True


def test_sql_worker_preserves_success_status_and_document_dlq() -> None:
    source = getsource(SqlDocumentAnalysisWorkerRepository._succeed_job)

    assert '"status": JobStatus.SUCCEEDED.value' in source, "AC-T4-WORKER-LIFECYCLE"
    assert DLQ_NAME == "document_analysis_dlq", "AC-T4-WORKER-LIFECYCLE"
