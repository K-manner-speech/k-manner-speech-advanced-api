from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.conversation import ConversationRepository


class InterviewRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._jobs = ConversationRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def create_setup(
        self, user_id: UUID, desired_role: str, application_type: str | None
    ) -> dict[str, Any]:
        row = (
            self._session.execute(
                text("""
                insert into public.interview_setups
                    (user_id, desired_role, application_type)
                values (:user_id, :desired_role, :application_type)
                returning id, desired_role, application_type, status, preparation_progress
            """),
                {
                    "user_id": user_id,
                    "desired_role": desired_role,
                    "application_type": application_type,
                },
            )
            .mappings()
            .one()
        )
        return dict(row)

    def setup_owned(self, user_id: UUID, setup_id: UUID) -> bool:
        return (
            self._session.execute(
                text("select 1 from public.interview_setups where id = :id and user_id = :user_id"),
                {"id": setup_id, "user_id": user_id},
            ).first()
            is not None
        )

    def create_document(
        self,
        user_id: UUID,
        setup_id: UUID,
        document_type: str,
        filename: str,
        storage_path: str,
        mime_type: str,
        size_bytes: int,
        extracted_text: str,
        replaced_document_id: UUID | None = None,
    ) -> dict[str, Any]:
        version = self._session.execute(
            text("""
                select coalesce(max(version_no), 0) + 1 from public.interview_documents
                where user_id = :user_id and setup_id = :setup_id and document_type = :document_type
            """),
            {"user_id": user_id, "setup_id": setup_id, "document_type": document_type},
        ).scalar_one()
        if replaced_document_id is not None:
            old = self._session.execute(
                text("""
                    update public.interview_documents
                    set is_current = false, deleted_at = now(), updated_at = now()
                    where id = :old_id and user_id = :user_id and is_current
                    returning id
                """),
                {"old_id": replaced_document_id, "user_id": user_id},
            ).first()
            if old is None:
                raise LookupError("document not found")
            self._cancel_document_jobs(replaced_document_id)
            self._delete_document_chunks(user_id, replaced_document_id)
        row = (
            self._session.execute(
                text("""
                insert into public.interview_documents
                    (setup_id, user_id, document_type, original_filename, storage_path,
                     mime_type, size_bytes, extracted_content, version_no, replaced_document_id)
                values
                    (:setup_id, :user_id, :document_type, :filename, :storage_path,
                     :mime_type, :size_bytes, cast(:extracted_content as jsonb),
                     :version, :replaced_id)
                returning id, setup_id, document_type, original_filename, mime_type,
                          size_bytes, version_no as version, is_current as current,
                          upload_status, analysis_status, uploaded_at
            """),
                {
                    "setup_id": setup_id,
                    "user_id": user_id,
                    "document_type": document_type,
                    "filename": filename,
                    "storage_path": storage_path,
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "extracted_content": json.dumps({"text": extracted_text}),
                    "version": version,
                    "replaced_id": replaced_document_id,
                },
            )
            .mappings()
            .one()
        )
        return dict(row)

    def list_documents(
        self, user_id: UUID, limit: int, document_type: str | None
    ) -> list[dict[str, Any]]:
        document_type_filter = ""
        parameters: dict[str, object] = {"user_id": user_id, "limit": limit}
        if document_type is not None:
            document_type_filter = "and document_type = :document_type"
            parameters["document_type"] = document_type
        rows = self._session.execute(
            text(f"""
                select id, setup_id, document_type, original_filename, mime_type,
                       size_bytes, version_no as version, is_current as current,
                       upload_status, analysis_status, uploaded_at
                from public.interview_documents
                where user_id = :user_id and is_current
                  {document_type_filter}
                order by uploaded_at desc, id desc limit :limit
            """),
            parameters,
        ).mappings()
        return [dict(row) for row in rows]

    def get_document(
        self, user_id: UUID, document_id: UUID, include_storage: bool = False
    ) -> dict[str, Any] | None:
        storage = ", storage_path, extracted_content" if include_storage else ""
        row = (
            self._session.execute(
                text(f"""
                select id, setup_id, document_type, original_filename, mime_type,
                       size_bytes, version_no as version, is_current as current,
                       upload_status, analysis_status, uploaded_at {storage}
                from public.interview_documents
                where id = :document_id and user_id = :user_id
            """),
                {"document_id": document_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row is not None else None

    def analyze_document(
        self, user_id: UUID, document_id: UUID, key: UUID, deadline_seconds: int
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        document = self.get_document(user_id, document_id, include_storage=True)
        if document is None or not document["current"]:
            return None
        active = self._session.execute(
            text("""
                select 1 from public.interview_document_analyses
                where document_id = :document_id and processing_status = 'processing'
            """),
            {"document_id": document_id},
        ).first()
        if active is not None:
            raise RuntimeError("document analysis already active")
        analysis = (
            self._session.execute(
                text("""
                insert into public.interview_document_analyses
                    (document_id, user_id, idempotency_key, deadline_at)
                values (:document_id, :user_id, :key, :deadline_at)
                returning id
            """),
                {
                    "document_id": document_id,
                    "user_id": user_id,
                    "key": key,
                    "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
                },
            )
            .mappings()
            .one()
        )
        self._session.execute(
            text(
                """
                update public.interview_documents
                set analysis_status = 'processing', updated_at = now()
                where id = :id
                """
            ),
            {"id": document_id},
        )
        job = self._jobs.insert_job(
            user_id,
            "interview_document_analysis",
            "interview_document_analysis_id",
            analysis["id"],
            deadline_seconds,
        )
        self._jobs.enqueue("document_analysis", job["id"], user_id)
        return {"id": analysis["id"], "version": document["version"]}, job

    def get_analysis(self, user_id: UUID, analysis_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text("""
                select a.id, a.document_id, d.version_no as document_version,
                       a.processing_status as status, a.extracted_data as extracted_sections,
                       a.citation_evidence, a.error_code
                from public.interview_document_analyses a
                join public.interview_documents d on d.id = a.document_id
                where a.id = :analysis_id and a.user_id = :user_id and d.user_id = :user_id
            """),
                {"analysis_id": analysis_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "id": row["id"],
            "document_id": row["document_id"],
            "document_version": row["document_version"],
            "status": row["status"],
            "extracted_sections": row["extracted_sections"] or {},
            "source_refs": [],
            "error": {"code": row["error_code"], "retryable": True} if row["error_code"] else None,
        }

    def delete_document(self, user_id: UUID, document_id: UUID) -> bool:
        row = self._session.execute(
            text("""
                update public.interview_documents
                set is_current = false,
                    extracted_content = '{}'::jsonb,
                    analysis_status = 'invalidated',
                    deleted_at = now(),
                    updated_at = now()
                where id = :document_id and user_id = :user_id and is_current
                returning id
            """),
            {"document_id": document_id, "user_id": user_id},
        ).first()
        if row is None:
            return False
        self._cancel_document_jobs(document_id)
        self._delete_document_chunks(user_id, document_id)
        self._session.execute(
            text(
                """
                update public.interview_document_analyses
                set processing_status = 'invalidated', completed_at = now(), updated_at = now()
                where document_id = :document_id
                  and processing_status in ('processing', 'succeeded')
                """
            ),
            {"document_id": document_id},
        )
        self._session.execute(
            text("delete from public.document_chunks where document_id = :document_id"),
            {"document_id": document_id},
        )
        self._session.execute(
            text("""
                update public.interview_configurations c set status = 'invalidated',
                    invalidated_at = now(), updated_at = now()
                where c.user_id = :user_id and c.status in ('processing', 'ready')
                  and exists (
                    select 1 from public.interview_document_analyses a
                    where a.document_id = :document_id and a.id = any(c.analysis_ids)
                  )
            """),
            {"user_id": user_id, "document_id": document_id},
        )
        return True

    def _delete_document_chunks(self, user_id: UUID, document_id: UUID) -> None:
        self._session.execute(
            text(
                "delete from public.document_chunks "
                "where document_id = :document_id and user_id = :user_id"
            ),
            {"document_id": document_id, "user_id": user_id},
        )

    def _cancel_document_jobs(self, document_id: UUID) -> None:
        self._session.execute(
            text("""
                update public.processing_jobs j
                set status = 'cancelled', progress_stage = null,
                    completed_at = now(), updated_at = now()
                from public.interview_document_analyses a
                where j.interview_document_analysis_id = a.id and a.document_id = :document_id
                  and j.status in ('queued', 'processing')
            """),
            {"document_id": document_id},
        )

    def create_configuration(
        self,
        user_id: UUID,
        setup_id: UUID,
        analysis_ids: list[UUID],
        conditions: dict[str, Any],
        question_count: int,
        key: UUID,
        deadline_seconds: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        owned_count = self._session.execute(
            text("""
                select count(*) from public.interview_document_analyses a
                join public.interview_documents d on d.id = a.document_id
                where a.id = any(:analysis_ids) and a.user_id = :user_id
                  and d.user_id = :user_id and d.setup_id = :setup_id
                  and d.is_current and a.processing_status = 'succeeded'
            """),
            {"analysis_ids": analysis_ids, "user_id": user_id, "setup_id": setup_id},
        ).scalar_one()
        if owned_count != len(set(analysis_ids)):
            raise LookupError("eligible analyses not found")
        version = self._session.execute(
            text(
                """
                select coalesce(max(version_no), 0) + 1
                from public.interview_configurations where setup_id = :setup_id
                """
            ),
            {"setup_id": setup_id},
        ).scalar_one()
        row = (
            self._session.execute(
                text("""
                insert into public.interview_configurations
                    (setup_id, user_id, version_no, idempotency_key, analysis_ids,
                     question_count, document_version_snapshot, deadline_at)
                values (:setup_id, :user_id, :version, :key, :analysis_ids,
                        :question_count, cast(:snapshot as jsonb), :deadline_at)
                returning id, version_no
            """),
                {
                    "setup_id": setup_id,
                    "user_id": user_id,
                    "version": version,
                    "key": key,
                    "analysis_ids": analysis_ids,
                    "question_count": question_count,
                    "snapshot": json.dumps({"conditions": conditions}),
                    "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
                },
            )
            .mappings()
            .one()
        )
        job = self._jobs.insert_job(
            user_id,
            "interview_configuration_generation",
            "interview_configuration_id",
            row["id"],
            deadline_seconds,
        )
        self._jobs.enqueue("document_analysis", job["id"], user_id)
        return dict(row), job

    def regenerate_configuration(
        self,
        user_id: UUID,
        configuration_id: UUID,
        conditions: dict[str, Any] | None,
        question_count: int | None,
        deadline_seconds: int,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        row = (
            self._session.execute(
                text("""
                select id, status, version_no, question_count, document_version_snapshot
                from public.interview_configurations
                where id = :id and user_id = :user_id for update
            """),
                {"id": configuration_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        if row["status"] not in {"failed", "ready"}:
            raise RuntimeError("configuration is not regenerable")
        active = self._session.execute(
            text("""
                select 1 from public.processing_jobs
                where interview_configuration_id = :id
                  and status in ('queued', 'processing')
            """),
            {"id": configuration_id},
        ).first()
        if active is not None:
            raise RuntimeError("configuration already has an active job")
        snapshot = dict(row["document_version_snapshot"] or {})
        if conditions is not None:
            snapshot["conditions"] = conditions
        self._session.execute(
            text("""
                update public.interview_configurations
                set status = 'processing', processing_token = gen_random_uuid(),
                    question_count = :question_count,
                    document_version_snapshot = cast(:snapshot as jsonb),
                    error_code = null, error_message = null, completed_at = null,
                    deadline_at = :deadline_at, next_attempt_at = null, updated_at = now()
                where id = :id
            """),
            {
                "id": configuration_id,
                "question_count": question_count or row["question_count"],
                "snapshot": json.dumps(snapshot),
                "deadline_at": datetime.now(UTC) + timedelta(seconds=deadline_seconds),
            },
        )
        job = self._jobs.insert_job(
            user_id,
            "interview_configuration_generation",
            "interview_configuration_id",
            configuration_id,
            deadline_seconds,
        )
        self._jobs.enqueue("document_analysis", job["id"], user_id)
        self._session.commit()
        return {"id": configuration_id, "version_no": row["version_no"]}, job

    def get_configuration(self, user_id: UUID, configuration_id: UUID) -> dict[str, Any] | None:
        row = (
            self._session.execute(
                text("""
                select id, setup_id, version_no, status, document_version_snapshot,
                       analysis_ids, question_count, error_code
                from public.interview_configurations
                where id = :id and user_id = :user_id
            """),
                {"id": configuration_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return {
            "id": row["id"],
            "setup_id": row["setup_id"],
            "version_no": row["version_no"],
            "status": row["status"],
            "document_version_snapshot": row["document_version_snapshot"],
            "analysis_ids": row["analysis_ids"],
            "question_count": row["question_count"],
            "error": {"code": row["error_code"], "retryable": True} if row["error_code"] else None,
        }

    def list_questions(
        self, user_id: UUID, configuration_id: UUID
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        configuration = self.get_configuration(user_id, configuration_id)
        if configuration is None:
            return None
        rows = self._session.execute(
            text("""
                select id, sequence_no as sequence, question_text as text,
                       question_type as type, is_required as required,
                       source_evidence as source_refs, evaluation_focus
                from public.interview_questions where configuration_id = :id
                order by sequence_no
            """),
            {"id": configuration_id},
        ).mappings()
        return configuration, [dict(row) for row in rows]

    def create_practice_room(self, user_id: UUID, configuration_id: UUID) -> dict[str, Any] | None:
        configuration = (
            self._session.execute(
                text("""
                select c.id, c.setup_id, c.status, s.desired_role
                from public.interview_configurations c
                join public.interview_setups s on s.id = c.setup_id
                where c.id = :id and c.user_id = :user_id for update of c
            """),
                {"id": configuration_id, "user_id": user_id},
            )
            .mappings()
            .one_or_none()
        )
        if configuration is None:
            return None
        if configuration["status"] != "ready":
            raise RuntimeError("configuration is not ready")
        first_question = (
            self._session.execute(
                text("""
                    select question_text
                    from public.interview_questions
                    where configuration_id = :id
                    order by sequence_no
                    limit 1
                """),
                {"id": configuration_id},
            )
            .mappings()
            .one_or_none()
        )
        if first_question is None:
            raise RuntimeError("configuration has no questions")
        self._session.execute(
            text(
                """
                update public.interview_configurations
                set status = 'in_progress', updated_at = now() where id = :id
                """
            ),
            {"id": configuration_id},
        )
        row = (
            self._session.execute(
                text("""
                insert into public.practice_rooms
                    (user_id, practice_type, interview_setup_id, interview_configuration_id, title)
                values (:user_id, 'interview', :setup_id, :configuration_id, :title)
                returning id, title, practice_type, persona_id, scenario_id, status,
                          turn_count, ended_reason, started_at, completed_at, updated_at
            """),
                {
                    "user_id": user_id,
                    "setup_id": configuration["setup_id"],
                    "configuration_id": configuration_id,
                    "title": configuration["desired_role"],
                },
            )
            .mappings()
            .one()
        )
        self._session.execute(
            text("""
                insert into public.room_messages
                    (room_id, sequence_no, sender_type, content,
                     delivery_status, persona_emotion)
                values
                    (:room_id, 1, 'persona', :question_text, 'sent', 'neutral')
            """),
            {"room_id": row["id"], "question_text": first_question["question_text"]},
        )
        return dict(row)
