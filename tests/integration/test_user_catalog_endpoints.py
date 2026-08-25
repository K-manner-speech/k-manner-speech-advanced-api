from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.auth import TokenClaims
from app.main import create_app
from app.routers.catalog import get_catalog_service
from app.routers.users import get_user_service
from app.schemas.catalog import PersonaDetail, PersonaSummary, ScenarioDetail, ScenarioSummary
from app.schemas.pagination import Page
from app.schemas.profile import (
    ConsentStatus,
    MeResponse,
    OnboardingStatus,
    ProfileData,
)
from app.services.catalog import CatalogService
from app.services.users import UserService
from tests.integration.test_auth_and_errors import StubTokenVerifier

USER_ID = uuid4()
PERSONA_ID = uuid4()
SCENARIO_ID = uuid4()
NOW = datetime.now(UTC)


def me_response(completed: bool = False) -> MeResponse:
    return MeResponse(
        profile=ProfileData(
            display_name="홍길동",
            birth_date=date(1995, 1, 2),
            gender="male",
            native_language="ko",
        ),
        display_language="ko",
        consents=[
            ConsentStatus(
                consent_type="terms",
                policy_version="v1",
                accepted=True,
            )
        ],
        onboarding_status=OnboardingStatus(
            completed=completed,
            missing_requirements=[] if completed else ["privacy"],
        ),
    )


class StubUserService(UserService):
    def get_me(self, user_id: Any) -> MeResponse:
        assert user_id == USER_ID
        return me_response()

    def replace_profile(self, user_id: Any, request: Any) -> MeResponse:
        assert user_id == USER_ID
        response = me_response()
        return response.model_copy(update={"profile": ProfileData(**request.model_dump())})

    def replace_language(self, user_id: Any, request: Any) -> MeResponse:
        response = me_response()
        return response.model_copy(update={"display_language": request.display_language})

    def replace_terms(self, user_id: Any, request: Any) -> MeResponse:
        return me_response()

    def complete_onboarding(self, user_id: Any) -> MeResponse:
        return me_response(completed=True)


class StubCatalogService(CatalogService):
    def list_personas(self, cursor: str | None, limit: int) -> Page[PersonaSummary]:
        return Page(
            items=[
                PersonaSummary(
                    id=PERSONA_ID,
                    name="면접관",
                    role_title="팀장",
                    description="실무 면접관",
                    avatar_key="interviewer",
                )
            ],
            next_cursor=None,
        )

    def get_persona(self, persona_id: Any) -> PersonaDetail:
        return PersonaDetail(
            id=PERSONA_ID,
            name="면접관",
            role_title="팀장",
            description="실무 면접관",
            avatar_key="interviewer",
            allowed_scenarios=[],
        )

    def list_scenarios(
        self,
        cursor: str | None,
        limit: int,
        persona_id: Any | None,
    ) -> Page[ScenarioSummary]:
        return Page(
            items=[
                ScenarioSummary(
                    id=SCENARIO_ID,
                    practice_type="scenario",
                    title="업무 요청",
                    goal="정중하게 요청하기",
                    location="사무실",
                    difficulty="medium",
                    estimated_minutes=5,
                )
            ],
            next_cursor=None,
        )

    def get_scenario(self, scenario_id: Any) -> ScenarioDetail:
        return ScenarioDetail(
            id=SCENARIO_ID,
            practice_type="scenario",
            title="업무 요청",
            goal="정중하게 요청하기",
            location="사무실",
            difficulty="medium",
            estimated_minutes=5,
            opening_message="부탁이 있습니다.",
            max_turns=5,
            required_conditions=[],
            allowed_personas=[],
        )


def client() -> TestClient:
    verifier = StubTokenVerifier(
        TokenClaims(
            sub=str(USER_ID),
            issuer="https://project.supabase.co/auth/v1",
            audience="authenticated",
        )
    )
    application = create_app(token_verifier=verifier)
    application.dependency_overrides[get_user_service] = lambda: StubUserService()
    application.dependency_overrides[get_catalog_service] = lambda: StubCatalogService()
    return TestClient(application)


AUTH = {"Authorization": "Bearer token"}


def test_user_onboarding_routes_are_exposed_and_owner_fields_are_rejected() -> None:
    api = client()

    assert api.get("/api/v1/me", headers=AUTH).status_code == 200
    profile_response = api.put(
        "/api/v1/me/profile",
        headers=AUTH,
        json={
            "display_name": "김하나",
            "birth_date": "1994-03-04",
            "gender": "female",
            "native_language": "ko",
        },
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["profile"]["display_name"] == "김하나"

    injected = api.put(
        "/api/v1/me/profile",
        headers=AUTH,
        json={
            "display_name": "김하나",
            "birth_date": "1994-03-04",
            "gender": "female",
            "native_language": "ko",
            "user_id": str(uuid4()),
            "onboarding_completed": True,
        },
    )
    assert injected.status_code == 422

    assert (
        api.put(
            "/api/v1/me/language",
            headers=AUTH,
            json={"display_language": "en"},
        ).status_code
        == 200
    )
    assert (
        api.put(
            "/api/v1/me/terms",
            headers=AUTH,
            json={
                "consents": [{"consent_type": "terms", "policy_version": "v1", "accepted": True}]
            },
        ).status_code
        == 200
    )
    assert (
        api.post(
            "/api/v1/me/onboarding/complete",
            headers={**AUTH, "Idempotency-Key": str(uuid4())},
            json={},
        ).json()["onboarding_status"]["completed"]
        is True
    )


def test_catalog_routes_return_safe_active_metadata() -> None:
    api = client()

    personas = api.get("/api/v1/personas?limit=10", headers=AUTH)
    scenarios = api.get("/api/v1/scenarios?limit=10", headers=AUTH)

    assert personas.status_code == 200
    assert personas.json()["items"][0]["id"] == str(PERSONA_ID)
    assert scenarios.status_code == 200
    assert scenarios.json()["items"][0]["id"] == str(SCENARIO_ID)
    assert api.get(f"/api/v1/personas/{PERSONA_ID}", headers=AUTH).status_code == 200
    assert api.get(f"/api/v1/scenarios/{SCENARIO_ID}", headers=AUTH).status_code == 200
