from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.core.errors import ApiError
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import (
    PersonaDetail,
    PersonaSummary,
    ScenarioDetail,
    ScenarioSummary,
)
from app.schemas.pagination import Page


class CatalogService(Protocol):
    def list_personas(self, cursor: str | None, limit: int) -> Page[PersonaSummary]: ...
    def get_persona(self, persona_id: UUID) -> PersonaDetail: ...
    def list_scenarios(
        self, cursor: str | None, limit: int, persona_id: UUID | None
    ) -> Page[ScenarioSummary]: ...
    def get_scenario(self, scenario_id: UUID) -> ScenarioDetail: ...


class SqlCatalogService:
    def __init__(self, repository: CatalogRepository, maximum_limit: int) -> None:
        self._repository = repository
        self._maximum_limit = maximum_limit

    def _validate_page(self, cursor: str | None, limit: int) -> None:
        if cursor is not None:
            raise ApiError(422, "INVALID_CURSOR", "페이지 커서가 유효하지 않습니다.")
        if limit > self._maximum_limit:
            raise ApiError(422, "PAGE_LIMIT_EXCEEDED", "페이지 크기가 허용 범위를 초과했습니다.")

    def list_personas(self, cursor: str | None, limit: int) -> Page[PersonaSummary]:
        self._validate_page(cursor, limit)
        return Page(
            items=[
                PersonaSummary.model_validate(row) for row in self._repository.list_personas(limit)
            ],
            next_cursor=None,
        )

    def get_persona(self, persona_id: UUID) -> PersonaDetail:
        row = self._repository.get_persona(persona_id)
        if row is None:
            raise ApiError(404, "PERSONA_NOT_FOUND", "페르소나를 찾을 수 없습니다.")
        return PersonaDetail(
            **row,
            allowed_scenarios=self._repository.persona_scenarios(persona_id),
        )

    def list_scenarios(
        self, cursor: str | None, limit: int, persona_id: UUID | None
    ) -> Page[ScenarioSummary]:
        self._validate_page(cursor, limit)
        return Page(
            items=[
                ScenarioSummary.model_validate(row)
                for row in self._repository.list_scenarios(limit, persona_id)
            ],
            next_cursor=None,
        )

    def get_scenario(self, scenario_id: UUID) -> ScenarioDetail:
        row = self._repository.get_scenario(scenario_id)
        if row is None:
            raise ApiError(404, "SCENARIO_NOT_FOUND", "시나리오를 찾을 수 없습니다.")
        return ScenarioDetail(
            **row,
            required_conditions=self._repository.scenario_conditions(scenario_id),
            allowed_personas=self._repository.scenario_personas(scenario_id),
        )
