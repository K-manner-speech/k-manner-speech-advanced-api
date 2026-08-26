import json
from typing import Any
from uuid import uuid4

import pytest

from app.adapters import account_auth
from app.adapters.account_auth import AuthReconfirmationError, SupabaseAccountAuthGateway


class StubResponse:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {}

    def __enter__(self) -> "StubResponse":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_reconfirm_user_uses_access_token_and_requires_matching_id(monkeypatch: Any) -> None:
    user_id = uuid4()
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> StubResponse:
        requests.append((request, timeout))
        return StubResponse({"id": str(user_id)})

    monkeypatch.setattr(account_auth, "urlopen", fake_urlopen)
    gateway = SupabaseAccountAuthGateway("https://project.supabase.co", "service-secret")

    gateway.reconfirm_user("access-token", user_id)

    request, timeout = requests[0]
    assert request.full_url.endswith("/auth/v1/user")
    assert request.get_method() == "GET"
    assert request.headers["Authorization"] == "Bearer access-token"
    assert timeout == 5

    monkeypatch.setattr(
        account_auth,
        "urlopen",
        lambda *_args, **_kwargs: StubResponse({"id": str(uuid4())}),
    )
    with pytest.raises(AuthReconfirmationError):
        gateway.reconfirm_user("access-token", user_id)


def test_delete_user_uses_server_secret_and_hard_delete(monkeypatch: Any) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: int) -> StubResponse:
        requests.append((request, timeout))
        return StubResponse()

    monkeypatch.setattr(account_auth, "urlopen", fake_urlopen)
    user_id = uuid4()

    SupabaseAccountAuthGateway(
        "https://project.supabase.co", "service-secret"
    ).delete_user(user_id)

    request, timeout = requests[0]
    assert f"/auth/v1/admin/users/{user_id}" in request.full_url
    assert "should_soft_delete=false" in request.full_url
    assert request.get_method() == "DELETE"
    assert request.headers["Authorization"] == "Bearer service-secret"
    assert timeout == 15
