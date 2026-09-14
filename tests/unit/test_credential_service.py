"""로그인 정보 변경. 실패를 화면이 그대로 옮겨 적을 수 있는 코드로 옮긴다."""

from __future__ import annotations

import pytest

from app.adapters.account_auth import (
    AuthGatewayUnavailable,
    AuthReconfirmationError,
    WrongPasswordError,
)
from app.core.errors import ApiError
from app.schemas.profile import PasswordChangeRequest
from app.services.credentials import SupabaseCredentialService


class FakeGateway:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    def reconfirm_user(self, access_token: str, expected_user_id: object) -> None: ...

    def delete_user(self, user_id: object) -> None: ...

    def get_email(self, access_token: str) -> str:
        return "minjun@example.com"

    def change_password(
        self, access_token: str, current_password: str, new_password: str
    ) -> None:
        self.calls.append(("password", access_token, current_password, new_password))
        if self.error:
            raise self.error


def service(error: Exception | None = None) -> tuple[SupabaseCredentialService, FakeGateway]:
    gateway = FakeGateway(error)
    return SupabaseCredentialService(gateway), gateway




def test_password_change_verifies_the_current_password_first() -> None:
    subject, gateway = service()

    subject.change_password(
        "token",
        PasswordChangeRequest(current_password="old-secret", new_password="new-secret-1"),
    )

    assert gateway.calls == [("password", "token", "old-secret", "new-secret-1")]


def test_wrong_current_password_does_not_look_like_our_fault() -> None:
    subject, _ = service(WrongPasswordError())

    with pytest.raises(ApiError) as error:
        subject.change_password(
            "token",
            PasswordChangeRequest(current_password="wrong", new_password="new-secret-1"),
        )

    assert error.value.status_code == 400
    assert error.value.code == "WRONG_PASSWORD"


def test_expired_session_asks_for_a_new_login() -> None:
    subject, _ = service(AuthReconfirmationError())

    with pytest.raises(ApiError) as error:
        subject.change_password(
            "token",
            PasswordChangeRequest(current_password="old", new_password="new-secret-1"),
        )

    assert error.value.status_code == 401


def test_auth_outage_is_retryable() -> None:
    """우리 잘못이 아니라 잠깐 닿지 않는 것이므로 다시 눌러 볼 수 있다."""
    subject, _ = service(AuthGatewayUnavailable())

    with pytest.raises(ApiError) as error:
        subject.change_password(
            "token",
            PasswordChangeRequest(current_password="old", new_password="new-secret-1"),
        )

    assert error.value.status_code == 503
    assert error.value.retryable is True
