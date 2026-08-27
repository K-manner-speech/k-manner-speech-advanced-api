from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ai.interfaces import AIProviderError

logger = logging.getLogger(__name__)


def post_json(
    endpoint: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: int,
    *,
    provider: str = "unknown",
) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            payload = json.loads(response.read())
    except HTTPError as error:
        request_id = error.headers.get("x-request-id") if error.headers else None
        logger.warning(
            "provider=%s error_type=%s http_status=%s request_id=%s",
            provider,
            type(error).__name__,
            error.code,
            request_id or "unknown",
        )
        retry_after = error.headers.get("Retry-After")
        try:
            retry_after_seconds = float(retry_after) if retry_after is not None else None
        except ValueError:
            retry_after_seconds = None
        raise AIProviderError(
            "AI_PROVIDER_UNAVAILABLE",
            retryable=error.code == 429 or error.code >= 500,
            retry_after_seconds=retry_after_seconds,
        ) from error
    except (URLError, TimeoutError, ValueError) as error:
        logger.warning(
            "provider=%s error_type=%s http_status=none request_id=unknown",
            provider,
            type(error).__name__,
        )
        raise AIProviderError("AI_PROVIDER_UNAVAILABLE", retryable=True) from error
    if not isinstance(payload, dict):
        raise AIProviderError(
            "AI_PROVIDER_SCHEMA_INVALID", retryable=False, schema_invalid=True
        )
    return payload
