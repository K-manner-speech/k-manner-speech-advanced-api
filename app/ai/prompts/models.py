"""Validated YAML prompt catalog models."""

from pydantic import BaseModel, ConfigDict, Field


class PromptFragment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int = Field(ge=1)
    description: str | None = None
    priority: int = 50
    enabled: bool = True
    prompt: str = Field(min_length=1)


class PromptReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    name: str


class PromptVoice(BaseModel):
    """페르소나를 소리로 읽을 때의 설정. 대화 내용이 아니라 TTS 입력이다."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    style: str | None = None


class PromptBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int = Field(ge=1)
    description: str | None = None
    voice: PromptVoice | None = None
    prompts: list[PromptReference]
