from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base model for strict API contracts."""

    model_config = ConfigDict(extra="forbid")
