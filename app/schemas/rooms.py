from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import StringConstraints, model_validator

from app.schemas.base import ContractModel

NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RoomCreateRequest(ContractModel):
    practice_type: Literal["free_chat", "scenario"]
    persona_id: UUID
    scenario_id: UUID | None = None

    @model_validator(mode="after")
    def require_scenario_for_scenario_practice(self) -> RoomCreateRequest:
        if self.practice_type == "scenario" and self.scenario_id is None:
            raise ValueError("scenario_id is required for scenario practice")
        return self


class MessageCreateRequest(ContractModel):
    content: NonBlankText
    input_mode: Literal["text", "voice"]
    current_interview_question_id: UUID | None = None
    client_request_id: UUID


class RepeatRequest(ContractModel):
    recommended_expression: NonBlankText


class EmotionSnapshot(ContractModel):
    status: Literal["processing", "succeeded", "failed"]
    label: str | None
    reasoning: str | None


class Room(ContractModel):
    id: UUID
    title: str
    practice_type: Literal["free_chat", "scenario", "interview"]
    persona_id: UUID | None
    scenario_id: UUID | None
    status: Literal["in_progress", "completed", "failed", "abandoned"]
    turn_count: int
    ended_reason: str | None
    started_at: datetime
    completed_at: datetime | None
    updated_at: datetime


class RoomSummary(Room):
    pass


class RoomDetail(Room):
    goal: str | None


class Message(ContractModel):
    id: UUID
    room_id: UUID
    sequence_no: int
    sender_type: Literal["user", "persona", "system"]
    content: str
    input_mode: Literal["text", "voice"] | None
    delivery_status: Literal["sending", "sent", "generating", "failed"]
    reply_to_message_id: UUID | None
    emotion: EmotionSnapshot | None
    created_at: datetime
    updated_at: datetime


class MessageAccepted(ContractModel):
    message: Message
    job: JobRef


from app.schemas.common import JobRef  # noqa: E402

MessageAccepted.model_rebuild()
