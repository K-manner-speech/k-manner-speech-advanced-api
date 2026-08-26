from __future__ import annotations

import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID


class AuthReconfirmationError(RuntimeError):
    pass


class AuthGatewayUnavailable(RuntimeError):
    pass


class AccountAuthGateway(Protocol):
    def reconfirm_user(self, access_token: str, expected_user_id: UUID) -> None: ...
    def delete_user(self, user_id: UUID) -> None: ...


class SupabaseAccountAuthGateway:
    def __init__(self, base_url: str, service_role_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_role_key = service_role_key

    def reconfirm_user(self, access_token: str, expected_user_id: UUID) -> None:
        request = Request(
            f"{self._base_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": self._service_role_key,
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=5) as response:  # noqa: S310
                payload = json.loads(response.read())
            if UUID(str(payload.get("id"))) != expected_user_id:
                raise AuthReconfirmationError
        except HTTPError as error:
            if error.code in {401, 403, 404}:
                raise AuthReconfirmationError from error
            raise AuthGatewayUnavailable from error
        except (URLError, TimeoutError, ValueError, TypeError, AttributeError) as error:
            raise AuthGatewayUnavailable from error

    def delete_user(self, user_id: UUID) -> None:
        request = Request(
            f"{self._base_url}/auth/v1/admin/users/{quote(str(user_id), safe='')}"
            "?should_soft_delete=false",
            headers={
                "Authorization": f"Bearer {self._service_role_key}",
                "apikey": self._service_role_key,
            },
            method="DELETE",
        )
        try:
            with urlopen(request, timeout=15):  # noqa: S310
                pass
        except HTTPError as error:
            if error.code == 404:
                return
            raise AuthGatewayUnavailable from error
        except (URLError, TimeoutError) as error:
            raise AuthGatewayUnavailable from error
