from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.base import ContractModel
from app.schemas.common import DomainRef

ResultStatus = Literal["processing", "partial", "succeeded", "failed"]


class SessionResultSummary(ContractModel):
    id: UUID
    attempt_no: int
    status: ResultStatus
    missing_categories: list[str]
    created_at: datetime


class ResultItem(ContractModel):
    item_type: str
    category: str | None
    title: str
    original_expression: str | None
    recommended_expression: str | None
    explanation: str | None
    evidence: str | None
    source_document_id: UUID | None
    order: int


class SessionResult(SessionResultSummary):
    items: list[ResultItem]
    source_refs: list[DomainRef]
