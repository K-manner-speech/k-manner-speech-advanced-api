from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class StorageSigner(Protocol):
    def create_signed_url(
        self, bucket: str, path: str, expires_in: int
    ) -> tuple[str, datetime]: ...


class StorageObjectStore(StorageSigner, Protocol):
    def upload(self, bucket: str, path: str, content: bytes, content_type: str) -> None: ...
    def delete(self, bucket: str, path: str) -> None: ...


class SupabaseStorageSigner:
    def __init__(self, base_url: str, service_role_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_role_key = service_role_key

    def create_signed_url(self, bucket: str, path: str, expires_in: int) -> tuple[str, datetime]:
        endpoint = (
            f"{self._base_url}/storage/v1/object/sign/{quote(bucket, safe='')}/"
            f"{quote(path, safe='/')}"
        )
        request = Request(
            endpoint,
            data=json.dumps({"expiresIn": expires_in}).encode(),
            headers={
                "Authorization": f"Bearer {self._service_role_key}",
                "apikey": self._service_role_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:  # noqa: S310
                payload = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise RuntimeError("storage signing failed") from error
        signed_path = payload.get("signedURL") or payload.get("signedUrl")
        if not isinstance(signed_path, str):
            raise RuntimeError("storage signing response is invalid")
        signed_url = (
            signed_path if signed_path.startswith("http") else f"{self._base_url}{signed_path}"
        )
        return signed_url, datetime.now(UTC) + timedelta(seconds=expires_in)

    def upload(self, bucket: str, path: str, content: bytes, content_type: str) -> None:
        endpoint = (
            f"{self._base_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(path, safe='/')}"
        )
        self._send(endpoint, "POST", content, content_type)

    def delete(self, bucket: str, path: str) -> None:
        endpoint = (
            f"{self._base_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(path, safe='/')}"
        )
        self._send(endpoint, "DELETE", None, None)

    def _send(
        self,
        endpoint: str,
        method: str,
        content: bytes | None,
        content_type: str | None,
    ) -> None:
        headers = {
            "Authorization": f"Bearer {self._service_role_key}",
            "apikey": self._service_role_key,
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        request = Request(endpoint, data=content, headers=headers, method=method)
        try:
            with urlopen(request, timeout=15):  # noqa: S310
                pass
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError("storage object operation failed") from error
