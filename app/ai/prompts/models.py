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


class PromptBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int = Field(ge=1)
    description: str | None = None
    prompts: list[PromptReference]
