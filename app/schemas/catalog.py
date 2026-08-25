from uuid import UUID

from app.schemas.base import ContractModel


class PersonaSummary(ContractModel):
    id: UUID
    name: str
    role_title: str | None
    description: str | None
    avatar_key: str | None


class ScenarioSummary(ContractModel):
    id: UUID
    practice_type: str
    title: str
    goal: str | None
    location: str | None
    difficulty: str | None
    estimated_minutes: int | None


class PersonaScenarioRef(ContractModel):
    scenario_id: UUID
    relationship_label: str | None


class PersonaDetail(PersonaSummary):
    allowed_scenarios: list[PersonaScenarioRef]


class RequiredCondition(ContractModel):
    condition_key: str
    description: str
    sort_order: int


class ScenarioPersonaRef(ContractModel):
    persona_id: UUID
    relationship_label: str | None


class ScenarioDetail(ScenarioSummary):
    opening_message: str | None
    max_turns: int | None
    required_conditions: list[RequiredCondition]
    allowed_personas: list[ScenarioPersonaRef]
