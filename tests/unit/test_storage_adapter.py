from __future__ import annotations

import io
import json
from urllib.error import HTTPError
from urllib.request import Request

import pytest

import app.adapters.storage as storage_module
from app.adapters.storage import SupabaseStorageSigner


def test_create_signed_url_adds_storage_api_prefix_to_relative_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def signed_response(request: Request, **_kwargs: object) -> io.BytesIO:
        assert request.full_url.endswith(
            "/storage/v1/object/sign/message-audio/user/room/audio.wav"
        )
        return io.BytesIO(
            json.dumps(
                {"signedURL": "/object/sign/message-audio/user/room/audio.wav?token=test-token"}
            ).encode()
        )

    monkeypatch.setattr(storage_module, "urlopen", signed_response)
    storage = SupabaseStorageSigner("https://project.supabase.co", "service-role-key")

    signed_url, _ = storage.create_signed_url(
        "message-audio", "user/room/audio.wav", 300
    )

    assert signed_url == (
        "https://project.supabase.co/storage/v1/object/sign/"
        "message-audio/user/room/audio.wav?token=test-token"
    )


def test_create_signed_url_preserves_absolute_provider_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_url = "https://cdn.example.test/audio.wav?token=test-token"

    def signed_response(*_args: object, **_kwargs: object) -> io.BytesIO:
        return io.BytesIO(json.dumps({"signedURL": provider_url}).encode())

    monkeypatch.setattr(storage_module, "urlopen", signed_response)
    storage = SupabaseStorageSigner("https://project.supabase.co", "service-role-key")

    signed_url, _ = storage.create_signed_url(
        "message-audio", "user/room/audio.wav", 300
    )

    assert signed_url == provider_url


def test_delete_treats_missing_storage_object_as_already_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_object(*_args: object, **_kwargs: object) -> object:
        raise HTTPError("https://storage.test/object", 404, "Not Found", None, None)

    monkeypatch.setattr(storage_module, "urlopen", missing_object)
    storage = SupabaseStorageSigner("https://project.supabase.co", "service-role-key")

    storage.delete("interview-documents", "user/setup/resume/missing.docx")


def test_delete_still_fails_for_non_404_storage_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise HTTPError("https://storage.test/object", 503, "Unavailable", None, None)

    monkeypatch.setattr(storage_module, "urlopen", unavailable)
    storage = SupabaseStorageSigner("https://project.supabase.co", "service-role-key")

    with pytest.raises(RuntimeError, match="storage object operation failed"):
        storage.delete("interview-documents", "user/setup/resume/file.docx")


def test_delete_accepts_legacy_400_response_with_no_such_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_object(*_args: object, **_kwargs: object) -> object:
        body = io.BytesIO(
            b'{"statusCode":"404","error":"not_found","message":"Object not found",'
            b'"code":"NoSuchKey"}'
        )
        raise HTTPError("https://storage.test/object", 400, "Bad Request", None, body)

    monkeypatch.setattr(storage_module, "urlopen", missing_object)
    storage = SupabaseStorageSigner("https://project.supabase.co", "service-role-key")

    storage.delete("interview-documents", "user/setup/resume/missing.docx")
