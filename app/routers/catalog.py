from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, get_authenticated_user
from app.core.config import AppSettings
from app.core.dependencies import get_session, get_settings
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import PersonaDetail, PersonaSummary, ScenarioDetail, ScenarioSummary
from app.schemas.pagination import Page
from app.services.catalog import CatalogService, SqlCatalogService

router = APIRouter(tags=["catalog"])


def get_catalog_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> CatalogService:
    return SqlCatalogService(CatalogRepository(session), settings.pagination_limit)


@router.get("/personas", operation_id="persona.list", response_model=Page[PersonaSummary])
def list_personas(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    limit: Annotated[int, Query(gt=0)],
    cursor: str | None = None,
) -> Page[PersonaSummary]:
    del user
    return service.list_personas(cursor, limit)


@router.get("/personas/{persona_id}", operation_id="persona.get", response_model=PersonaDetail)
def get_persona(
    persona_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> PersonaDetail:
    del user
    return service.get_persona(persona_id)


@router.get("/scenarios", operation_id="scenario.list", response_model=Page[ScenarioSummary])
def list_scenarios(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    limit: Annotated[int, Query(gt=0)],
    cursor: str | None = None,
    persona_id: UUID | None = None,
) -> Page[ScenarioSummary]:
    del user
    return service.list_scenarios(cursor, limit, persona_id)


@router.get(
    "/scenarios/{scenario_id}",
    operation_id="scenario.get",
    response_model=ScenarioDetail,
)
def get_scenario(
    scenario_id: UUID,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ScenarioDetail:
    del user
    return service.get_scenario(scenario_id)
