"""면접 근거 저장·조회가 배포된 스키마와 어긋나지 않는지 지킨다.

같은 계약을 검사하던 테스트가 있었지만 대상이 실행되지 않는 구현이어서,
살아 있는 경로의 SQL 이 틀려도 통과했다. 대상을 옮겨 다시 물게 한다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from inspect import getsource
from typing import Any
from uuid import uuid4

from app.adapters.interview_provider import (
    GeneratedQuestion,
    InterviewQuestionResult,
    QuestionSourceRef,
)
from app.schemas.common import JobType
from worker.domain_adapters import ConfigurationAdapter, DocumentAnalysisAdapter
from worker.executors import ConfigurationOutput
from worker.queue import ClaimedJob
from worker.sql_queue import SqlEvidenceRetriever


def test_chunk_persistence_and_retrieval_use_the_deployed_columns() -> None:
    persistence = getsource(DocumentAnalysisAdapter.complete)
    retrieval = getsource(SqlEvidenceRetriever.retrieve)

    for sql in (persistence, retrieval):
        assert "public.document_chunks" in sql
        assert "public.interview_document_chunks" not in sql
    for column in ("document_version", "section", "source_ref", "embedding"):
        assert column in persistence, column
    for column in ("document_version", "section", "content"):
        assert column in retrieval, column


class _Session:
    """execute 로 넘어온 파라미터만 모아 두는 가짜 세션."""

    def __init__(self) -> None:
        self.parameters: list[dict[str, Any]] = []

    def execute(self, _statement: object, parameters: dict[str, Any] | None = None) -> Any:
        if parameters is not None:
            self.parameters.append(parameters)

        class _Result:
            def first(self) -> tuple[int]:
                return (1,)

        return _Result()


def _configuration_job() -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(), job_type=JobType.INTERVIEW_CONFIGURATION_GENERATION,
        user_id=uuid4(), target_id=uuid4(), processing_token=uuid4(),
        attempt_count=1, schema_repair_count=0, deadline_at=datetime.now(UTC),
        payload={},
    )


def test_question_source_refs_are_stored_as_json_with_string_uuids() -> None:
    """UUID 를 그대로 넘기면 jsonb 캐스팅에서 깨진다."""
    chunk_id, document_id = uuid4(), uuid4()
    output = ConfigurationOutput(
        questions=InterviewQuestionResult(
            questions=[
                GeneratedQuestion(
                    sequence=1, text="JWT 경험을 설명해 주세요.", type="required",
                    required=True,
                    source_refs=[QuestionSourceRef(
                        evidence_no=1, section="resume", chunk_id=chunk_id,
                        document_id=document_id, evidence=None)],
                    evaluation_focus=["구체성"],
                )
            ]
        ),
        evidence=[],
    )
    session = _Session()

    assert ConfigurationAdapter().complete(session, _configuration_job(), output) is True

    stored = next(p["source_refs"] for p in session.parameters if "source_refs" in p)
    assert json.loads(str(stored)) == [
        {
            "evidence_no": 1,
            "section": "resume",
            "chunk_id": str(chunk_id),
            "document_id": str(document_id),
            "evidence": None,
        }
    ]
