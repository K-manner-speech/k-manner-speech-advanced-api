from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from app.repositories.users import UserRepository
from app.services.users import SqlUserService


def test_get_me_projects_repository_row_to_safe_profile_contract() -> None:
    repository = MagicMock(spec=UserRepository)
    repository.get_profile.return_value = {
        "display_name": "홍길동",
        "birth_date": date(1995, 1, 2),
        "gender": "male",
        "native_language": "ko",
        "display_language": "ko",
        "onboarding_completed": False,
    }
    repository.list_active_consents.return_value = []

    response = SqlUserService(repository).get_me(uuid4())

    assert response.profile.model_dump() == {
        "display_name": "홍길동",
        "birth_date": date(1995, 1, 2),
        "gender": "male",
        "native_language": "ko",
    }
    assert response.display_language == "ko"
    assert response.onboarding_status.completed is False
