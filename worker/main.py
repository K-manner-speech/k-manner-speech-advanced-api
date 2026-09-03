from __future__ import annotations

import argparse
import logging
import os
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from uuid import uuid4

from app.adapters.storage import SupabaseStorageSigner
from app.ai.providers.gemini import GeminiSpeechClient, GeminiStructuredClient
from app.ai.providers.openai import OpenAIEmbeddingClient, OpenAIResponsesClient
from app.core.config import BASE_QUEUE_NAMES
from app.core.dependencies import get_session_factory, get_settings
from app.schemas.common import JobType
from worker.domain_adapters import (
    ConfigurationAdapter,
    ConversationAdapter,
    DocumentAnalysisAdapter,
    EmotionAdapter,
    FeedbackAdapter,
    GoalProgressAdapter,
    SessionResultAdapter,
    TTSAdapter,
)
from worker.executors import WorkerExecutors
from worker.heartbeat import HeartbeatRepository
from worker.queue import QueueWorker
from worker.sql_queue import SqlDomainAdapter, SqlEvidenceRetriever, SqlQueueRepository
from worker.tts_streaming import TTSChunkWriter

logger = logging.getLogger(__name__)


def run_queue(queue_name: str) -> None:
    if queue_name not in BASE_QUEUE_NAMES:
        raise ValueError(f"unknown base queue: {queue_name}")
    # 설정이 없으면 logging 은 WARNING 이상만 내보낸다. worker 가 남기는 진행
    # 로그가 통째로 사라져 무슨 일이 있었는지 알 수 없으므로 여기서 붙인다.
    logging.basicConfig(
        level=os.getenv("WORKER_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    with ThreadPoolExecutor(
        max_workers=settings.worker_concurrency + 1,
        thread_name_prefix=f"{queue_name}-worker",
    ) as executor:
        futures = [
            executor.submit(_run_consumer, queue_name, index)
            for index in range(settings.worker_concurrency)
        ]
        futures.append(executor.submit(_run_deadline_reaper, queue_name))
        done, _pending = wait(futures, return_when=FIRST_EXCEPTION)
        for future in done:
            error = future.exception()
            if error is None:
                continue
            # 여기서 예외를 그대로 올리면 ThreadPoolExecutor 의 __exit__ 가
            # 영원히 도는 나머지 스레드를 기다리느라 끝나지 않는다. 프로세스는
            # 살아 있는데 아무 일도 하지 않고 traceback 도 남지 않아서, 겉으로는
            # 정상처럼 보이는 좀비가 된다. 즉시 소리 내며 죽는다.
            logger.critical(
                "worker thread died queue=%s — 프로세스를 종료한다", queue_name, exc_info=error
            )
            logging.shutdown()
            os._exit(1)


def _run_consumer(queue_name: str, consumer_index: int) -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    worker_id = f"{queue_name}-{consumer_index}-{uuid4()}"
    started_at = datetime.now(UTC)
    with session_factory() as session:
        storage = SupabaseStorageSigner(
            settings.supabase_url,
            settings.supabase_service_role_key.get_secret_value(),
        )
        all_adapters: dict[JobType, SqlDomainAdapter] = {
            JobType.CONVERSATION_TEXT: ConversationAdapter(storage),
            JobType.EMOTION_ANALYSIS: EmotionAdapter(),
            JobType.TTS_GENERATION: TTSAdapter(storage),
            JobType.TURN_FEEDBACK: FeedbackAdapter(),
            JobType.INTERVIEW_DOCUMENT_ANALYSIS: DocumentAnalysisAdapter(),
            JobType.INTERVIEW_CONFIGURATION_GENERATION: ConfigurationAdapter(),
            JobType.SESSION_RESULT_GENERATION: SessionResultAdapter(),
            JobType.SCENARIO_GOAL_PROGRESS: GoalProgressAdapter(),
        }
        adapters = {
            job_type: adapter
            for job_type, adapter in all_adapters.items()
            if _queue_for(job_type) == queue_name
        }
        repository = SqlQueueRepository(
            session,
            queue_name,
            settings.worker_visibility_timeout_seconds,
            adapters,
        )
        gemini_chat = GeminiStructuredClient(
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_chat_model,
            15,
        )
        executors = WorkerExecutors(
            gemini_chat=gemini_chat,
            token_counter=gemini_chat,
            gemini_emotion=GeminiStructuredClient(
                settings.gemini_api_key.get_secret_value(),
                settings.gemini_emotion_model,
                15,
            ),
            gemini_tts=GeminiSpeechClient(
                settings.gemini_api_key.get_secret_value(),
                settings.gemini_tts_model,
                45,
            ),
            openai_feedback=OpenAIResponsesClient(
                settings.openai_api_key.get_secret_value(),
                settings.openai_feedback_model,
                30,
            ),
            openai_interview=OpenAIResponsesClient(
                settings.openai_api_key.get_secret_value(),
                settings.openai_interview_model,
                60,
                max_output_tokens=6000,
            ),
            embeddings=OpenAIEmbeddingClient(
                settings.openai_api_key.get_secret_value(),
                settings.openai_embedding_model,
                60,
                dimensions=settings.openai_embedding_dimensions,
            ),
            evidence_retriever=SqlEvidenceRetriever(session_factory),
            rag_threshold=settings.rag_similarity_threshold,
            context_summary_trigger_tokens=settings.context_summary_trigger_tokens,
            tts_chunk_writer=TTSChunkWriter(session_factory).append,
        )
        worker = QueueWorker(repository, executors, maximum_attempts=3)
        heartbeat = HeartbeatRepository(session)
        while True:
            # 하트비트는 job 처리와 무관한 부가 기록이다. 여기서 실패해 루프를
            # 벗어나면 job 을 하나도 처리하지 못하는 상태로 남는다. readiness 가
            # 하트비트 부재로 알려줄 테니 로그만 남기고 계속 돈다.
            try:
                heartbeat.record(worker_id, queue_name, started_at)
            except Exception:
                session.rollback()
                logger.exception("heartbeat failed queue=%s", queue_name)
            try:
                if not worker.run_once():
                    time.sleep(0.25)
            except Exception:
                session.rollback()
                logger.exception("job processing failed queue=%s", queue_name)
                time.sleep(0.25)


def _run_deadline_reaper(queue_name: str) -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    storage = SupabaseStorageSigner(
        settings.supabase_url,
        settings.supabase_service_role_key.get_secret_value(),
    )
    all_adapters: dict[JobType, SqlDomainAdapter] = {
        JobType.CONVERSATION_TEXT: ConversationAdapter(),
        JobType.EMOTION_ANALYSIS: EmotionAdapter(),
        JobType.TTS_GENERATION: TTSAdapter(storage),
        JobType.TURN_FEEDBACK: FeedbackAdapter(),
        JobType.INTERVIEW_DOCUMENT_ANALYSIS: DocumentAnalysisAdapter(),
        JobType.INTERVIEW_CONFIGURATION_GENERATION: ConfigurationAdapter(),
        JobType.SESSION_RESULT_GENERATION: SessionResultAdapter(),
        JobType.SCENARIO_GOAL_PROGRESS: GoalProgressAdapter(),
    }
    adapters = {
        job_type: adapter
        for job_type, adapter in all_adapters.items()
        if _queue_for(job_type) == queue_name
    }
    with session_factory() as session:
        repository = SqlQueueRepository(
            session,
            queue_name,
            settings.worker_visibility_timeout_seconds,
            adapters,
        )
        while True:
            try:
                repository.recover_expired()
            except Exception:
                session.rollback()
                logger.exception("deadline recovery failed queue=%s", queue_name)
            time.sleep(0.25)


def _queue_for(job_type: JobType) -> str:
    from worker.runtime import JOB_QUEUE_NAMES

    return JOB_QUEUE_NAMES[job_type]


def main() -> None:
    parser = argparse.ArgumentParser(description="K-Manner background worker")
    parser.add_argument("--queue", choices=BASE_QUEUE_NAMES, required=True)
    arguments = parser.parse_args()
    run_queue(arguments.queue)


if __name__ == "__main__":
    main()
