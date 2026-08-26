from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.readiness import ReadinessReport
from app.main import create_app


class StubReadinessChecker:
    def __init__(self, report: ReadinessReport) -> None:
        self.report = report
        self.call_count = 0

    async def check(self) -> ReadinessReport:
        self.call_count += 1
        return self.report


def test_live_returns_ok_without_running_readiness_checks() -> None:
    checker = StubReadinessChecker(ReadinessReport.all_failed())
    client = TestClient(create_app(readiness_checker=checker))

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert checker.call_count == 0


def test_ready_returns_all_named_checks_when_every_check_passes() -> None:
    checker = StubReadinessChecker(ReadinessReport.all_healthy())
    client = TestClient(create_app(readiness_checker=checker))

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "ok",
            "pgmq_queues": "ok",
            "required_extensions": "ok",
            "timeout_policies": "ok",
            "config": "ok",
            "worker_heartbeat": "ok",
        },
    }
    assert checker.call_count == 1


def test_ready_returns_safe_503_envelope_for_failed_checks() -> None:
    checker = StubReadinessChecker(
        ReadinessReport(
            database=True,
            pgmq_queues=False,
            required_extensions=True,
            timeout_policies=False,
            config=True,
            worker_heartbeat=True,
        )
    )
    client = TestClient(create_app(readiness_checker=checker))

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "SERVICE_NOT_READY"
    assert payload["message"] == "서비스가 요청을 받을 준비가 되지 않았습니다."
    assert payload["fields"] == {"failed_checks": ["pgmq_queues", "timeout_policies"]}
    assert payload["field_errors"] == []
    UUID(payload["request_id"])
    assert payload["retryable"] is True
    assert "database_url" not in response.text.lower()
    assert "exception" not in response.text.lower()


def test_default_app_fails_closed_until_adapters_are_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app())

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["fields"] == {
        "failed_checks": [
            "database",
            "pgmq_queues",
            "required_extensions",
            "timeout_policies",
            "config",
            "worker_heartbeat",
        ]
    }


def test_openapi_uses_versioned_health_paths_and_operation_ids() -> None:
    client = TestClient(create_app())

    openapi = client.get("/openapi.json").json()

    assert openapi["paths"]["/api/v1/health/live"]["get"]["operationId"] == "health.live"
    ready_operation = openapi["paths"]["/api/v1/health/ready"]["get"]
    assert ready_operation["operationId"] == "health.ready"
    assert set(ready_operation["responses"]) >= {"200", "503"}
    assert "/health/live" not in openapi["paths"]
