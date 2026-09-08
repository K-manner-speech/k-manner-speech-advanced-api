from __future__ import annotations

import hashlib
import io
import re
import zipfile
from contextlib import suppress
from pathlib import PurePath
from uuid import UUID, uuid4
from xml.etree import ElementTree

from pypdf import PdfReader

from app.adapters.storage import StorageObjectStore
from app.core.errors import ApiError
from app.repositories.interviews import InterviewRepository
from app.schemas.common import JobRef
from app.schemas.interviews import (
    AnalysisAccepted,
    ConfigurationAccepted,
    InterviewAnalysis,
    InterviewConfiguration,
    InterviewConfigurationGenerateRequest,
    InterviewConfigurationRegenerateRequest,
    InterviewDocument,
    InterviewQuestion,
    InterviewQuestionList,
    InterviewSetup,
    InterviewSetupCreateRequest,
)
from app.schemas.pagination import Page
from app.schemas.rooms import Room
from app.services.idempotency import IdempotencyRepository, request_fingerprint
from app.services.jobs import get_job_execution_policy

DOCUMENT_BUCKET = "interview-documents"
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class SqlInterviewService:
    def __init__(
        self,
        repository: InterviewRepository,
        storage: StorageObjectStore,
        pagination_limit: int,
        document_min_text_chars: int,
        idempotency: IdempotencyRepository | None = None,
        idempotency_lease_seconds: int = 30,
        idempotency_retention_seconds: int = 86400,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._pagination_limit = pagination_limit
        self._document_min_text_chars = document_min_text_chars
        self._idempotency = idempotency
        self._idempotency_lease_seconds = idempotency_lease_seconds
        self._idempotency_retention_seconds = idempotency_retention_seconds

    def create_setup(
        self, user_id: UUID, request: InterviewSetupCreateRequest, key: UUID
    ) -> InterviewSetup:
        if self._idempotency is None:
            raise RuntimeError("idempotency repository is required")
        action_scope = "interview_setup.create"
        claim = self._idempotency.claim(
            user_id,
            action_scope,
            key,
            request_fingerprint(request.model_dump(mode="json")),
            self._idempotency_lease_seconds,
        )
        if claim.kind == "replay":
            return InterviewSetup.model_validate(claim.response_body)

        if claim.claim_token is None:
            raise RuntimeError("idempotency claim token is missing")

        try:
            row = self._repository.create_setup(
                user_id, request.desired_role, request.application_type
            )
            response = InterviewSetup.model_validate(row)
            self._idempotency.complete(
                user_id,
                action_scope,
                key,
                claim.claim_token,
                201,
                response.model_dump(mode="json"),
                "InterviewSetup.v1",
                self._idempotency_retention_seconds,
            )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return response

    def upload_document(
        self,
        user_id: UUID,
        setup_id: UUID,
        document_type: str,
        filename: str,
        content_type: str,
        content: bytes,
        key: UUID,
        replaced_document_id: UUID | None = None,
    ) -> InterviewDocument:
        if not self._repository.setup_owned(user_id, setup_id):
            raise ApiError(404, "INTERVIEW_SETUP_NOT_FOUND", "면접 설정을 찾을 수 없습니다.")
        safe_name = PurePath(filename).name
        mime_type, extension, extracted_text = self._validate_and_extract(
            document_type, content_type, content
        )
        claim = None
        if self._idempotency is not None and replaced_document_id is None:
            claim = self._idempotency.claim(
                user_id,
                "interview_document.create",
                key,
                request_fingerprint(
                    {
                        "setup_id": setup_id,
                        "document_type": document_type,
                        "filename": safe_name,
                        "content_type": mime_type,
                        "content_sha256": hashlib.sha256(content).hexdigest(),
                    }
                ),
                self._idempotency_lease_seconds,
                self._idempotency_retention_seconds,
            )
            if claim.kind == "replay":
                assert claim.response_body is not None
                return InterviewDocument.model_validate(claim.response_body)
        path = f"{user_id}/{setup_id}/{document_type}/{uuid4()}{extension}"
        try:
            self._storage.upload(DOCUMENT_BUCKET, path, content, mime_type)
            row = self._repository.create_document(
                user_id,
                setup_id,
                document_type,
                safe_name,
                path,
                mime_type,
                len(content),
                extracted_text,
                replaced_document_id,
            )
            response = InterviewDocument.model_validate(row)
            if (
                self._idempotency is not None
                and claim is not None
                and claim.claim_token is not None
            ):
                self._idempotency.complete(
                    user_id,
                    "interview_document.create",
                    key,
                    claim.claim_token,
                    201,
                    response.model_dump(mode="json"),
                    "v1",
                    self._idempotency_retention_seconds,
                )
            self._repository.commit()
        except RuntimeError as error:
            raise ApiError(
                503,
                "STORAGE_UNAVAILABLE",
                "문서를 저장할 수 없습니다.",
                retryable=True,
            ) from error
        except LookupError as error:
            with suppress(RuntimeError):
                self._storage.delete(DOCUMENT_BUCKET, path)
            raise ApiError(
                404, "INTERVIEW_DOCUMENT_NOT_FOUND", "교체할 문서를 찾을 수 없습니다."
            ) from error
        return response

    def list_documents(
        self,
        user_id: UUID,
        cursor: str | None,
        limit: int | None,
        document_type: str | None,
    ) -> Page[InterviewDocument]:
        if cursor is not None:
            raise ApiError(422, "INVALID_CURSOR", "현재 cursor를 해석할 수 없습니다.")
        size = min(limit or self._pagination_limit, self._pagination_limit)
        rows = self._repository.list_documents(user_id, size, document_type)
        return Page(
            items=[InterviewDocument.model_validate(row) for row in rows],
            next_cursor=None,
        )

    def get_document(self, user_id: UUID, document_id: UUID) -> InterviewDocument:
        row = self._repository.get_document(user_id, document_id)
        if row is None:
            raise ApiError(404, "INTERVIEW_DOCUMENT_NOT_FOUND", "문서를 찾을 수 없습니다.")
        return InterviewDocument.model_validate(row)

    def analyze_document(self, user_id: UUID, document_id: UUID, key: UUID) -> AnalysisAccepted:
        document = self._repository.get_document(user_id, document_id, include_storage=True)
        if document is None or not document["current"]:
            raise ApiError(404, "INTERVIEW_DOCUMENT_NOT_FOUND", "문서를 찾을 수 없습니다.")
        extracted = document.get("extracted_content") or {}
        if len(str(extracted.get("text", "")).strip()) < self._document_min_text_chars:
            raise ApiError(
                422,
                "DOCUMENT_TEXT_NOT_EXTRACTABLE",
                "분석할 수 있는 텍스트가 충분하지 않습니다.",
            )
        claim = None
        if self._idempotency is not None:
            claim = self._idempotency.claim(
                user_id,
                "interview_document.analyze",
                key,
                request_fingerprint({"document_id": document_id}),
                self._idempotency_lease_seconds,
                self._idempotency_retention_seconds,
            )
            if claim.kind == "replay":
                assert claim.response_body is not None
                return AnalysisAccepted.model_validate(claim.response_body)
        try:
            value = self._repository.analyze_document(
                user_id,
                document_id,
                key,
                get_job_execution_policy("interview_document_analysis").deadline_seconds,
            )
        except RuntimeError as error:
            raise ApiError(409, "DOCUMENT_ANALYSIS_ACTIVE", str(error)) from error
        if value is None:
            raise ApiError(404, "INTERVIEW_DOCUMENT_NOT_FOUND", "문서를 찾을 수 없습니다.")
        analysis, job = value
        response = AnalysisAccepted(
            analysis_id=analysis["id"],
            document_id=document_id,
            document_version=analysis["version"],
            job=JobRef(job_id=job["id"], type=job["type"], status=job["status"]),
        )
        if self._idempotency is not None and claim is not None and claim.claim_token is not None:
            self._idempotency.complete(
                user_id,
                "interview_document.analyze",
                key,
                claim.claim_token,
                202,
                response.model_dump(mode="json"),
                "v1",
                self._idempotency_retention_seconds,
            )
        self._repository.commit()
        return response

    def delete_document(self, user_id: UUID, document_id: UUID, key: UUID) -> None:
        del key
        document = self._repository.get_document(user_id, document_id, include_storage=True)
        if document is None or not document["current"]:
            raise ApiError(404, "INTERVIEW_DOCUMENT_NOT_FOUND", "문서를 찾을 수 없습니다.")
        if not self._repository.delete_document(user_id, document_id):
            self._repository.rollback()
            raise ApiError(
                409,
                "DOCUMENT_STATE_CHANGED",
                "문서 상태가 변경되었습니다.",
                retryable=True,
            )
        try:
            self._storage.delete(DOCUMENT_BUCKET, document["storage_path"])
        except RuntimeError as error:
            self._repository.rollback()
            raise ApiError(
                503,
                "STORAGE_UNAVAILABLE",
                "원본 문서를 삭제할 수 없습니다.",
                retryable=True,
            ) from error
        self._repository.commit()

    def get_analysis(self, user_id: UUID, analysis_id: UUID) -> InterviewAnalysis:
        row = self._repository.get_analysis(user_id, analysis_id)
        if row is None:
            raise ApiError(404, "INTERVIEW_ANALYSIS_NOT_FOUND", "분석 결과를 찾을 수 없습니다.")
        return InterviewAnalysis.model_validate(row)

    def generate_configuration(
        self,
        user_id: UUID,
        request: InterviewConfigurationGenerateRequest,
        key: UUID,
    ) -> ConfigurationAccepted:
        if not self._repository.setup_owned(user_id, request.setup_id):
            raise ApiError(404, "INTERVIEW_SETUP_NOT_FOUND", "면접 설정을 찾을 수 없습니다.")
        claim = None
        if self._idempotency is not None:
            claim = self._idempotency.claim(
                user_id,
                "interview_configuration.generate",
                key,
                request_fingerprint(request.model_dump(mode="json")),
                self._idempotency_lease_seconds,
                self._idempotency_retention_seconds,
            )
            if claim.kind == "replay":
                assert claim.response_body is not None
                return ConfigurationAccepted.model_validate(claim.response_body)
        try:
            configuration, job = self._repository.create_configuration(
                user_id,
                request.setup_id,
                request.analysis_ids,
                request.question_count,
                key,
                get_job_execution_policy("interview_configuration_generation").deadline_seconds,
            )
        except LookupError as error:
            raise ApiError(
                422, "ANALYSIS_NOT_ELIGIBLE", "사용 가능한 최신 분석이 아닙니다."
            ) from error
        response = ConfigurationAccepted(
            configuration_id=configuration["id"],
            version_no=configuration["version_no"],
            job=JobRef(job_id=job["id"], type=job["type"], status=job["status"]),
        )
        if self._idempotency is not None and claim is not None and claim.claim_token is not None:
            self._idempotency.complete(
                user_id,
                "interview_configuration.generate",
                key,
                claim.claim_token,
                202,
                response.model_dump(mode="json"),
                "v1",
                self._idempotency_retention_seconds,
            )
        self._repository.commit()
        return response

    def get_configuration(self, user_id: UUID, configuration_id: UUID) -> InterviewConfiguration:
        row = self._repository.get_configuration(user_id, configuration_id)
        if row is None:
            raise ApiError(
                404, "INTERVIEW_CONFIGURATION_NOT_FOUND", "면접 구성을 찾을 수 없습니다."
            )
        return InterviewConfiguration.model_validate(row)

    def list_questions(self, user_id: UUID, configuration_id: UUID) -> InterviewQuestionList:
        value = self._repository.list_questions(user_id, configuration_id)
        if value is None:
            raise ApiError(
                404, "INTERVIEW_CONFIGURATION_NOT_FOUND", "면접 구성을 찾을 수 없습니다."
            )
        configuration, rows = value
        if configuration["status"] not in {"ready", "in_progress", "completed"}:
            raise ApiError(
                409,
                "CONFIGURATION_NOT_READY",
                "질문이 아직 준비되지 않았습니다.",
                retryable=True,
            )
        return InterviewQuestionList(
            configuration_id=configuration_id,
            version_no=configuration["version_no"],
            status=configuration["status"],
            questions=[InterviewQuestion.model_validate(row) for row in rows],
        )

    def regenerate_configuration(
        self,
        user_id: UUID,
        configuration_id: UUID,
        request: InterviewConfigurationRegenerateRequest,
        key: UUID,
    ) -> ConfigurationAccepted:
        del key
        try:
            value = self._repository.regenerate_configuration(
                user_id,
                configuration_id,
                request.question_count,
                get_job_execution_policy("interview_configuration_generation").deadline_seconds,
            )
        except RuntimeError as error:
            raise ApiError(409, "CONFIGURATION_NOT_REGENERABLE", str(error)) from error
        if value is None:
            raise ApiError(
                404, "INTERVIEW_CONFIGURATION_NOT_FOUND", "면접 구성을 찾을 수 없습니다."
            )
        configuration, job = value
        return ConfigurationAccepted(
            configuration_id=configuration["id"],
            version_no=configuration["version_no"],
            job=JobRef(job_id=job["id"], type=job["type"], status=job["status"]),
        )

    def create_practice_room(self, user_id: UUID, configuration_id: UUID, key: UUID) -> Room:
        claim = None
        if self._idempotency is not None:
            claim = self._idempotency.claim(
                user_id,
                "interview_practice_room.create",
                key,
                request_fingerprint({"configuration_id": configuration_id}),
                self._idempotency_lease_seconds,
                self._idempotency_retention_seconds,
            )
            if claim.kind == "replay":
                assert claim.response_body is not None
                return Room.model_validate(claim.response_body)
        try:
            row = self._repository.create_practice_room(user_id, configuration_id)
        except RuntimeError as error:
            raise ApiError(409, "CONFIGURATION_NOT_READY", str(error)) from error
        if row is None:
            raise ApiError(
                404, "INTERVIEW_CONFIGURATION_NOT_FOUND", "면접 구성을 찾을 수 없습니다."
            )
        response = Room.model_validate(row)
        if self._idempotency is not None and claim is not None and claim.claim_token is not None:
            self._idempotency.complete(
                user_id,
                "interview_practice_room.create",
                key,
                claim.claim_token,
                201,
                response.model_dump(mode="json"),
                "v1",
                self._idempotency_retention_seconds,
            )
        self._repository.commit()
        return response

    def _validate_and_extract(
        self, document_type: str, content_type: str, content: bytes
    ) -> tuple[str, str, str]:
        if len(content) > MAX_DOCUMENT_BYTES:
            raise ApiError(413, "DOCUMENT_TOO_LARGE", "문서는 10MB 이하여야 합니다.")
        if document_type not in {"resume", "portfolio", "self_introduction"}:
            raise ApiError(422, "INVALID_DOCUMENT_TYPE", "지원하지 않는 문서 유형입니다.")
        try:
            if content.startswith(b"%PDF-") and content_type == PDF_MIME:
                reader = PdfReader(io.BytesIO(content))
                text_value = "\n".join(page.extract_text() or "" for page in reader.pages)
                return PDF_MIME, ".pdf", text_value
            if (
                content.startswith(b"PK")
                and content_type == DOCX_MIME
                and document_type != "portfolio"
            ):
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    xml = archive.read("word/document.xml")
                root = ElementTree.fromstring(xml)
                text_value = " ".join(
                    node.text or "" for node in root.iter() if node.tag.endswith("}t")
                )
                return DOCX_MIME, ".docx", re.sub(r"\s+", " ", text_value).strip()
        except (ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
            raise ApiError(
                415, "DOCUMENT_PARSE_FAILED", "문서 형식을 확인할 수 없습니다."
            ) from error
        raise ApiError(
            415,
            "UNSUPPORTED_DOCUMENT_MEDIA_TYPE",
            "문서 형식과 MIME이 일치하지 않습니다.",
        )
