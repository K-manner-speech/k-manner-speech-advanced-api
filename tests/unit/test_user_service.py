from datetime import date
from typing import Any, cast
from uuid import uuid4

import pytest

from app.core.errors import ApiError
from app.repositories.users import UserRepository
from app.services.users import SqlUserService


class StubUserRepository:
    def __init__(self, profile: dict[str, Any] | None) -> None:
        self.profile = profile

    def get_profile(self, _user_id: object) -> dict[str, Any] | None:
        return self.profile

    def list_active_consents(self, _user_id: object) -> list[dict[str, object]]:
        return []


def test_get_me_splits_repository_row_into_strict_response_fields() -> None:
    service = SqlUserService(
        cast(
            UserRepository,
            StubUserRepository(
                {
                    "display_name": "홍길동",
                    "birth_date": date(1995, 1, 2),
                    "gender": "male",
                    "native_language": "ko",
                    "display_language": "ko",
                    "onboarding_completed": False,
                }
            ),
        )
    )

    response = service.get_me(uuid4())

    assert response.profile.model_dump() == {
        "display_name": "홍길동",
        "birth_date": date(1995, 1, 2),
        "gender": "male",
        "native_language": "ko",
    }
    assert response.display_language == "ko"
    assert response.onboarding_status.completed is False


def test_get_me_keeps_profile_not_found_contract() -> None:
    service = SqlUserService(cast(UserRepository, StubUserRepository(None)))

    with pytest.raises(ApiError) as captured:
        service.get_me(uuid4())

    assert captured.value.status_code == 404
    assert captured.value.code == "PROFILE_NOT_FOUND"
