from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import ContractModel


class AudioAccessResponse(ContractModel):
    status: Literal["processing", "ready", "failed"]
    signed_url: str | None
    expires_at: datetime | None
    audio_type: str
    duration_ms: int | None = None


class RepeatRequest(ContractModel):
    recommended_expression: str = Field(min_length=1, max_length=2000)
