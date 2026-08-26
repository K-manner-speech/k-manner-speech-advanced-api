from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.interview_provider import (
    EmbeddingProvider,
    InterviewAnalysisResult,
    InterviewProvider,
    InterviewProviderError,
    InterviewQuestionResult,
    OpenAIEmbeddingProvider,
    OpenAIInterviewProvider,
)
from app.core.dependencies import get_session_factory, get_settings
from app.rag.interview import DocumentChunk, chunk_document
from app.schemas.common import JobStatus
from worker.heartbeat import HeartbeatRepository

QUEUE_NAME = "document_analysis"
DLQ_NAME = "document_analysis_dlq"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QueueMessage:
    message_id: int
    job_id: UUID


@dataclass(frozen=True, slots=True)
class WorkItem:
    job_id: UUID
    job_type: str
    target_id: UUID
    processing_token: UUID
    attempt_count: int
    payload: dict[str, Any]


class WorkerRepository(Protocol):
    def read_one(self) -> QueueMessage | None: ...
    def claim(self, job_id: UUID) -> WorkItem | None: ...
    def complete_analysis(
        self,
        item: WorkItem,
        result: InterviewAnalysisResult,
        chunks: list[DocumentChunk],
        embeddings: list[list[float]],
    ) -> bool: ...
    def retrieve_evidence(
        self,
        item: WorkItem,
        query_embedding: list[float],
        threshold: float,
        limit: int,
    ) -> list[dict[str, Any]]: ...
    def complete_configuration(self, item: WorkItem, result: InterviewQuestionResult) -> bool: ...
    def retry(self, item: WorkItem, code: str) -> None: ...
    def fail(self, item: WorkItem, code: str) -> None: ...
    def acknowledge(self, message_id: int) -> None: ...
    def rollback(self) -> None: ...


class DocumentAnalysisWorker:
    def __init__(
        self,
        repository: WorkerRepository,
        provider: InterviewProvider,
        embedding_provider: EmbeddingProvider,
        maximum_attempts: int,
        similarity_threshold: float = 0.7,
        retrieval_limit: int = 8,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._embedding_provider = embedding_provider
        self._maximum_attempts = maximum_attempts
        self._similarity_threshold = similarity_threshold
        self._retrieval_limit = retrieval_limit

    def run_once(self) -> bool:
        message = self._repository.read_one()
        if message is None:
            return False
        item = self._repository.claim(message.job_id)
        if item is None:
            self._repository.acknowledge(message.message_id)
            return True
        try:
            if item.job_type == "interview_document_analysis":
                chunks = chunk_document(str(item.payload["extracted_text"]))
                if not chunks:
                    self._repository.fail(item, "INTERVIEW_DOCUMENT_TEXT_EMPTY")
                    self._repository.acknowledge(message.message_id)
                    return True
                embeddings = self._embedding_provider.embed([chunk.text for chunk in chunks])
                analysis_result = self._provider.analyze_document(
                    str(item.payload["extracted_text"])
                )
                completed = self._repository.complete_analysis(
                    item, analysis_result, chunks, embeddings
                )
            elif item.job_type == "interview_configuration_generation":
                query_embedding = self._embedding_provider.embed(
                    [str(item.payload["retrieval_query"])]
                )[0]
                evidence = self._repository.retrieve_evidence(
                    item,
                    query_embedding,
                    self._similarity_threshold,
                    self._retrieval_limit,
                )
                if not evidence:
                    self._repository.fail(item, "INTERVIEW_RAG_EVIDENCE_NOT_FOUND")
                    self._repository.acknowledge(message.message_id)
                    return True
                question_result = self._provider.generate_questions(
                    {"evidence": evidence},
                    dict(item.payload["conditions"]),
                    int(item.payload["question_count"]),
                )
                completed = self._repository.complete_configuration(item, question_result)
            else:
                self._repository.fail(item, "UNSUPPORTED_DOCUMENT_JOB")
                self._repository.acknowledge(message.message_id)
                return True
        except InterviewProviderError as error:
            if error.retryable and item.attempt_count < self._maximum_attempts:
                self._repository.retry(item, error.code)
            else:
                self._repository.fail(item, error.code)
            self._repository.acknowledge(message.message_id)
            return True
        except Exception:
            self._repository.rollback()
            self._repository.fail(item, "UNEXPECTED_DOCUMENT_JOB_ERROR")
            self._repository.acknowledge(message.message_id)
            return True
        if not completed:
            return False
        self._repository.acknowledge(message.message_id)
        return True


class SqlDocumentAnalysisWorkerRepository:
    def __init__(self, session: Session, visibility_timeout_seconds: int = 65) -> None:
        self._session = session
        self._visibility_timeout_seconds = visibility_timeout_seconds

    def read_one(self) -> QueueMessage | None:
        row = (
            self._session.execute(
                text("select msg_id, message from pgmq.read(:queue, :visibility_timeout, 1)"),
                {
                    "queue": QUEUE_NAME,
                    "visibility_timeout": self._visibility_timeout_seconds,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        try:
            return QueueMessage(
                message_id=row["msg_id"],
                job_id=UUID(str(row["message"]["job_id"])),
            )
        except (KeyError, TypeError, ValueError):
            self.acknowledge(row["msg_id"])
            return None

    def claim(self, job_id: UUID) -> WorkItem | None:
        job = (
            self._session.execute(
                text(
                    """
                    select id, user_id, job_type, interview_document_analysis_id,
                           interview_configuration_id, transport_attempt_count
                    from public.processing_jobs
                    where id = :job_id and status = 'queued'
                      and job_type in (
                        'interview_document_analysis',
                        'interview_configuration_generation'
                      )
                    for update
                    """
                ),
                {"job_id": job_id},
            )
            .mappings()
            .one_or_none()
        )
        if job is None:
            self._session.rollback()
            return None
        job_type = str(job["job_type"])
        target_id = (
            job["interview_document_analysis_id"]
            if job_type == "interview_document_analysis"
            else job["interview_configuration_id"]
        )
        stage = (
            "extracting_text"
            if job_type == "interview_document_analysis"
            else "retrieving_evidence"
        )
        self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = 'processing', progress_stage = :stage,
                    transport_attempt_count = transport_attempt_count + 1,
                    started_at = coalesce(started_at, now()), updated_at = now()
                where id = :job_id and status = 'queued'
                """
            ),
            {"job_id": job_id, "stage": stage},
        )
        if job_type == "interview_document_analysis":
            target = (
                self._session.execute(
                    text(
                        """
                        update public.interview_document_analyses a
                        set attempt_count = attempt_count + 1, updated_at = now()
                        from public.interview_documents d
                        where a.id = :target_id and d.id = a.document_id
                          and a.processing_status = 'processing'
                        returning a.processing_token,
                                  coalesce(d.extracted_content->>'text', '') as extracted_text
                        """
                    ),
                    {"target_id": target_id},
                )
                .mappings()
                .one_or_none()
            )
            payload = {"extracted_text": target["extracted_text"]} if target else None
        else:
            target = (
                self._session.execute(
                    text(
                        """
                        update public.interview_configurations c
                        set attempt_count = attempt_count + 1, updated_at = now()
                        from public.interview_setups s
                        where c.id = :target_id and c.status = 'processing'
                          and s.id = c.setup_id
                        returning c.processing_token, c.question_count,
                                  coalesce(c.document_version_snapshot->'conditions', '{}'::jsonb)
                                    as conditions,
                                  c.analysis_ids, s.desired_role
                        """
                    ),
                    {"target_id": target_id},
                )
                .mappings()
                .one_or_none()
            )
            payload = (
                {
                    "user_id": job["user_id"],
                    "analysis_ids": target["analysis_ids"],
                    "retrieval_query": json.dumps(
                        {
                            "desired_role": target["desired_role"],
                            "conditions": target["conditions"],
                        },
                        ensure_ascii=False,
                    ),
                    "conditions": dict(target["conditions"]),
                    "question_count": target["question_count"],
                }
                if target
                else None
            )
        if target is None or payload is None:
            self._session.rollback()
            return None
        self._session.commit()
        return WorkItem(
            job_id=job_id,
            job_type=job_type,
            target_id=target_id,
            processing_token=target["processing_token"],
            attempt_count=int(job["transport_attempt_count"]) + 1,
            payload=payload,
        )

    def complete_analysis(
        self,
        item: WorkItem,
        result: InterviewAnalysisResult,
        chunks: list[DocumentChunk],
        embeddings: list[list[float]],
    ) -> bool:
        if len(chunks) != len(embeddings):
            raise InterviewProviderError("INTERVIEW_EMBEDDING_SCHEMA_INVALID", retryable=False)
        locked = (
            self._session.execute(
                text(
                    """
                select a.document_id, a.user_id, d.version_no as document_version
                from public.interview_document_analyses a
                join public.interview_documents d on d.id = a.document_id
                where a.id = :target_id and a.processing_token = :token
                  and a.processing_status = 'processing'
                for update of a
                """
                ),
                {"target_id": item.target_id, "token": item.processing_token},
            )
            .mappings()
            .one_or_none()
        )
        if locked is None:
            self._session.rollback()
            return False
        self._session.execute(
            text(
                """
                delete from public.document_chunks
                where document_id = :document_id and document_version = :document_version
                """
            ),
            {
                "document_id": locked["document_id"],
                "document_version": locked["document_version"],
            },
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self._session.execute(
                text(
                    """
                    insert into public.document_chunks
                        (user_id, document_id, analysis_id, document_version, chunk_index,
                         section, content, token_count, source_ref, embedding)
                    values (:user_id, :document_id, :analysis_id, :document_version, :chunk_index,
                            :section, :content, :token_count, cast(:source_ref as jsonb),
                            cast(:embedding as extensions.vector))
                    """
                ),
                {
                    "user_id": locked["user_id"],
                    "document_id": locked["document_id"],
                    "analysis_id": item.target_id,
                    "document_version": locked["document_version"],
                    "chunk_index": chunk.index,
                    "section": "document",
                    "content": chunk.text,
                    "token_count": chunk.token_estimate,
                    "source_ref": json.dumps(
                        {
                            "analysis_id": str(item.target_id),
                            "chunk_index": chunk.index,
                        }
                    ),
                    "embedding": "[" + ",".join(str(value) for value in embedding) + "]",
                },
            )
        updated = self._session.execute(
            text(
                """
                update public.interview_document_analyses
                set processing_status = 'succeeded', extracted_data = cast(:sections as jsonb),
                    citation_evidence = cast(:citations as jsonb), error_code = null,
                    completed_at = now(), updated_at = now()
                where id = :target_id and processing_token = :token
                  and processing_status = 'processing'
                returning document_id
                """
            ),
            {
                "target_id": item.target_id,
                "token": item.processing_token,
                "sections": json.dumps(result.sections.model_dump(), ensure_ascii=False),
                "citations": json.dumps(
                    [citation.model_dump() for citation in result.citations], ensure_ascii=False
                ),
            },
        ).first()
        if updated is None:
            self._session.rollback()
            return False
        self._session.execute(
            text(
                """
                update public.interview_documents
                set processing_status = 'ready', analysis_status = 'succeeded',
                    processed_at = now(), updated_at = now()
                where id = :document_id
                """
            ),
            {"document_id": updated[0]},
        )
        self._succeed_job(item.job_id)
        self._session.commit()
        return True

    def retrieve_evidence(
        self,
        item: WorkItem,
        query_embedding: list[float],
        threshold: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text(
                """
                select ch.id as chunk_id, ch.document_id, ch.analysis_id, ch.chunk_index,
                       ch.content,
                       1 - (ch.embedding <=> cast(:embedding as extensions.vector)) as similarity
                from public.document_chunks ch
                join public.interview_document_analyses a on a.id = ch.analysis_id
                join public.interview_documents d on d.id = ch.document_id
                where ch.user_id = :user_id
                  and ch.analysis_id = any(:analysis_ids)
                  and a.processing_status = 'succeeded'
                  and d.is_current and d.upload_status <> 'deleted'
                  and 1 - (ch.embedding <=> cast(:embedding as extensions.vector)) >= :threshold
                order by ch.embedding <=> cast(:embedding as extensions.vector), ch.id
                limit :limit
                """
            ),
            {
                "embedding": "[" + ",".join(str(value) for value in query_embedding) + "]",
                "user_id": item.payload["user_id"],
                "analysis_ids": item.payload["analysis_ids"],
                "threshold": threshold,
                "limit": limit,
            },
        ).mappings()
        return [dict(row) for row in rows]

    def complete_configuration(self, item: WorkItem, result: InterviewQuestionResult) -> bool:
        locked = self._session.execute(
            text(
                """
                select 1 from public.interview_configurations
                where id = :target_id and processing_token = :token and status = 'processing'
                for update
                """
            ),
            {"target_id": item.target_id, "token": item.processing_token},
        ).first()
        if locked is None:
            self._session.rollback()
            return False
        self._session.execute(
            text("delete from public.interview_questions where configuration_id = :target_id"),
            {"target_id": item.target_id},
        )
        for question in result.questions:
            self._session.execute(
                text(
                    """
                    insert into public.interview_questions
                        (configuration_id, sequence_no, question_text, question_type,
                         is_required, source_evidence, evaluation_focus)
                    values (:configuration_id, :sequence, :question_text, :question_type,
                            :required, cast(:source_refs as jsonb),
                            cast(:evaluation_focus as jsonb))
                    """
                ),
                {
                    "configuration_id": item.target_id,
                    "sequence": question.sequence,
                    "question_text": question.text,
                    "question_type": question.type,
                    "required": question.required,
                    "source_refs": json.dumps(
                        [source.model_dump(mode="json") for source in question.source_refs],
                        ensure_ascii=False,
                    ),
                    "evaluation_focus": json.dumps(question.evaluation_focus, ensure_ascii=False),
                },
            )
        self._session.execute(
            text(
                """
                update public.interview_configurations
                set status = 'ready', error_code = null, error_message = null,
                    completed_at = now(), updated_at = now()
                where id = :target_id and processing_token = :token
                """
            ),
            {"target_id": item.target_id, "token": item.processing_token},
        )
        self._succeed_job(item.job_id)
        self._session.commit()
        return True

    def retry(self, item: WorkItem, code: str) -> None:
        self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = 'queued', progress_stage = null, error_code = :code,
                    error_retryable = true, updated_at = now()
                where id = :job_id and status = 'processing'
                """
            ),
            {"job_id": item.job_id, "code": code},
        )
        self._session.execute(
            text("select pgmq.send(:queue, cast(:payload as jsonb))"),
            {"queue": QUEUE_NAME, "payload": json.dumps({"job_id": str(item.job_id)})},
        )
        self._session.commit()

    def fail(self, item: WorkItem, code: str) -> None:
        if item.job_type == "interview_document_analysis":
            self._session.execute(
                text(
                    """
                    update public.interview_document_analyses
                    set processing_status = 'failed', error_code = :code,
                        completed_at = now(), updated_at = now()
                    where id = :target_id and processing_token = :token
                    """
                ),
                {"target_id": item.target_id, "token": item.processing_token, "code": code},
            )
        else:
            self._session.execute(
                text(
                    """
                    update public.interview_configurations
                    set status = 'failed', error_code = :code,
                        completed_at = now(), updated_at = now()
                    where id = :target_id and processing_token = :token
                    """
                ),
                {"target_id": item.target_id, "token": item.processing_token, "code": code},
            )
        self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = 'failed', progress_stage = null, error_code = :code,
                    error_retryable = false, completed_at = now(), updated_at = now()
                where id = :job_id and status = 'processing'
                """
            ),
            {"job_id": item.job_id, "code": code},
        )
        self._session.execute(
            text("select pgmq.send(:queue, cast(:payload as jsonb))"),
            {
                "queue": DLQ_NAME,
                "payload": json.dumps({"job_id": str(item.job_id), "error_code": code}),
            },
        )
        self._session.commit()

    def acknowledge(self, message_id: int) -> None:
        self._session.execute(
            text("select pgmq.delete(:queue, :message_id)"),
            {"queue": QUEUE_NAME, "message_id": message_id},
        )
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def _succeed_job(self, job_id: UUID) -> None:
        self._session.execute(
            text(
                """
                update public.processing_jobs
                set status = :status, progress_stage = null, error_code = null,
                    error_retryable = null, completed_at = now(), updated_at = now()
                where id = :job_id and status = 'processing'
                """
            ),
            {"job_id": job_id, "status": JobStatus.SUCCEEDED.value},
        )


def main() -> None:
    settings = get_settings()
    session = get_session_factory()()
    provider = OpenAIInterviewProvider(
        settings.openai_api_key.get_secret_value(), settings.openai_interview_model
    )
    embedding_provider = OpenAIEmbeddingProvider(
        settings.openai_api_key.get_secret_value(),
        settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimensions,
    )
    repository = SqlDocumentAnalysisWorkerRepository(session)
    worker = DocumentAnalysisWorker(
        repository,
        provider,
        embedding_provider,
        maximum_attempts=3,
        similarity_threshold=settings.rag_similarity_threshold,
    )
    heartbeat = HeartbeatRepository(session)
    worker_id = f"document-analysis-{UUID(int=0)}"
    started_at = datetime.now(UTC)
    try:
        while True:
            heartbeat.record(worker_id, QUEUE_NAME, started_at)
            try:
                if not worker.run_once():
                    time.sleep(1)
            except Exception:
                session.rollback()
                LOGGER.exception("document analysis worker loop recovered from an error")
                time.sleep(1)
    except KeyboardInterrupt:
        return
    finally:
        session.close()


if __name__ == "__main__":
    main()
