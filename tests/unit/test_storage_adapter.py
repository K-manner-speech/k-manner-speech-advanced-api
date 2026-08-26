from __future__ import annotations

import io
from urllib.error import HTTPError

import pytest

import app.adapters.storage as storage_module
from app.adapters.storage import SupabaseStorageSigner


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
