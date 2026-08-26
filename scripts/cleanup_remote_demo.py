from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app.adapters.storage import SupabaseStorageSigner
from app.core.dependencies import get_engine, get_settings
from app.services.interviews import DOCUMENT_BUCKET


def load_test_env() -> None:
    for line in Path(".env.test").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", maxsplit=1)
            os.environ.setdefault(key, value)


def main() -> None:
    load_test_env()
    email = os.environ["SUPABASE_TEST_EMAIL"]
    settings = get_settings()
    engine = get_engine()
    storage = SupabaseStorageSigner(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value()
    )
    with engine.connect() as connection:
        user_id = connection.execute(
            text("select id from auth.users where email = :email"), {"email": email}
        ).scalar_one()
        if not isinstance(user_id, UUID):
            raise RuntimeError("test user was not resolved to a UUID")
        keep_document_ids = list(
            connection.execute(
                text(
                    """
                    select distinct document_id
                    from public.interview_document_analyses
                    where user_id = :user_id and processing_status = 'succeeded'
                    """
                ),
                {"user_id": user_id},
            ).scalars()
        )
        removable_documents = list(
            connection.execute(
                text(
                    """
                    select id, storage_path
                    from public.interview_documents
                    where user_id = :user_id and not (id = any(:keep_ids))
                    order by id
                    """
                ),
                {"user_id": user_id, "keep_ids": keep_document_ids},
            ).mappings()
        )
        job_ids = list(
            connection.execute(
                text("select id from public.processing_jobs where user_id = :user_id"),
                {"user_id": user_id},
            ).scalars()
        )

    for document in removable_documents:
        storage.delete(DOCUMENT_BUCKET, str(document["storage_path"]))

    deleted_queue_messages = 0
    with engine.begin() as connection:
        if job_ids:
            for queue_name in ("document_analysis", "conversation_text"):
                message_ids = list(
                    connection.execute(
                        text(
                            f"select msg_id from pgmq.q_{queue_name} "
                            "where message->>'job_id' = any(:job_ids)"
                        ),
                        {"job_ids": [str(job_id) for job_id in job_ids]},
                    ).scalars()
                )
                for message_id in message_ids:
                    connection.execute(
                        text("select pgmq.delete(:queue_name, :message_id)"),
                        {"queue_name": queue_name, "message_id": message_id},
                    )
                    deleted_queue_messages += 1

        deleted_jobs = connection.execute(
            text("delete from public.processing_jobs where user_id = :user_id"),
            {"user_id": user_id},
        ).rowcount
        deleted_rooms = connection.execute(
            text("delete from public.practice_rooms where user_id = :user_id"),
            {"user_id": user_id},
        ).rowcount
        deleted_configurations = connection.execute(
            text("delete from public.interview_configurations where user_id = :user_id"),
            {"user_id": user_id},
        ).rowcount
        deleted_analyses = connection.execute(
            text(
                """
                delete from public.interview_document_analyses
                where user_id = :user_id and processing_status <> 'succeeded'
                """
            ),
            {"user_id": user_id},
        ).rowcount
        deleted_documents = connection.execute(
            text(
                """
                delete from public.interview_documents
                where user_id = :user_id and not (id = any(:keep_ids))
                """
            ),
            {"user_id": user_id, "keep_ids": keep_document_ids},
        ).rowcount
        deleted_setups = connection.execute(
            text(
                """
                delete from public.interview_setups s
                where s.user_id = :user_id
                  and not exists (
                    select 1 from public.interview_documents d where d.setup_id = s.id
                  )
                """
            ),
            {"user_id": user_id},
        ).rowcount

    engine.dispose()
    print(
        "REMOTE_DEMO_CLEANUP_OK "
        f"kept_documents={len(keep_document_ids)} "
        f"deleted_documents={deleted_documents} deleted_analyses={deleted_analyses} "
        f"deleted_configurations={deleted_configurations} deleted_rooms={deleted_rooms} "
        f"deleted_jobs={deleted_jobs} deleted_setups={deleted_setups} "
        f"deleted_queue_messages={deleted_queue_messages}"
    )


if __name__ == "__main__":
    main()
