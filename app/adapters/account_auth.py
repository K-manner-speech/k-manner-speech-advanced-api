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


class WrongPasswordError(RuntimeError):
    """현재 비밀번호가 틀렸다. 새 비밀번호로 넘어가지 않는다."""


class AccountAuthGateway(Protocol):
    def reconfirm_user(self, access_token: str, expected_user_id: UUID) -> None: ...
    def delete_user(self, user_id: UUID) -> None: ...
    def get_email(self, access_token: str) -> str: ...
    def change_password(
        self, access_token: str, current_password: str, new_password: str
    ) -> None: ...


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

    def get_email(self, access_token: str) -> str:
        """지금 로그인한 계정의 주소. 비밀번호 확인에 쓰려면 주소가 필요하다."""
        payload = self._user_payload(access_token)
        email = payload.get("email")
        if not isinstance(email, str) or not email:
            raise AuthGatewayUnavailable
        return email

    def change_password(
        self, access_token: str, current_password: str, new_password: str
    ) -> None:
        """현재 비밀번호를 확인한 뒤 바꾼다.

        세션만으로 바꾸게 두면 잠기지 않은 화면을 잠깐 만진 사람이 계정을
        가져갈 수 있다. 확인은 지금 주소와 현재 비밀번호로 한 번 로그인해
        보는 것으로 한다.
        """
        email = self.get_email(access_token)
        self._verify_password(email, current_password)
        try:
            self._update_user(access_token, {"password": new_password})
        except HTTPError as error:
            raise AuthGatewayUnavailable from error

    def _verify_password(self, email: str, password: str) -> None:
        request = Request(
            f"{self._base_url}/auth/v1/token?grant_type=password",
            data=json.dumps({"email": email, "password": password}).encode(),
            headers={
                "apikey": self._service_role_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=10):  # noqa: S310
                return
        except HTTPError as error:
            if error.code in {400, 401, 403}:
                raise WrongPasswordError from error
            raise AuthGatewayUnavailable from error
        except (URLError, TimeoutError) as error:
            raise AuthGatewayUnavailable from error

    def _update_user(self, access_token: str, body: dict[str, str]) -> None:
        request = Request(
            f"{self._base_url}/auth/v1/user",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": self._service_role_key,
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        try:
            with urlopen(request, timeout=10):  # noqa: S310
                return
        except (URLError, TimeoutError) as error:
            if isinstance(error, HTTPError):
                raise
            raise AuthGatewayUnavailable from error

    def _user_payload(self, access_token: str) -> dict[str, object]:
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
        except HTTPError as error:
            if error.code in {401, 403, 404}:
                raise AuthReconfirmationError from error
            raise AuthGatewayUnavailable from error
        except (URLError, TimeoutError, ValueError) as error:
            raise AuthGatewayUnavailable from error
        if not isinstance(payload, dict):
            raise AuthGatewayUnavailable
        return payload
