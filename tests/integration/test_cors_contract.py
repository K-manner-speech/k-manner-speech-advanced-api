from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app
from tests.unit.test_core_config import complete_settings


def test_cors_allows_only_configured_exact_origin_and_headers() -> None:
    settings = AppSettings(_env_file=None, **complete_settings())
    client = TestClient(create_app(settings=settings))

    allowed = client.options(
        "/api/v1/health/live",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Idempotency-Key",
        },
    )
    blocked = client.options(
        "/api/v1/health/live",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "authorization" in allowed.headers["access-control-allow-headers"].lower()
    assert blocked.status_code == 400
