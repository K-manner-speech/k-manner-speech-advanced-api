from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.readiness import ReadinessChecker
from app.schemas.common import ErrorEnvelope
from app.schemas.health import HealthChecks, HealthLive, HealthReady

router = APIRouter(prefix="/health", tags=["health"])


def get_readiness_checker() -> ReadinessChecker:
    raise RuntimeError("readiness checker dependency is not configured")


@router.get("/live", operation_id="health.live", response_model=HealthLive)
async def get_live() -> HealthLive:
    return HealthLive()


@router.get(
    "/ready",
    operation_id="health.ready",
    response_model=HealthReady,
    responses={503: {"model": ErrorEnvelope}},
)
async def get_ready(
    readiness_checker: Annotated[ReadinessChecker, Depends(get_readiness_checker)],
) -> HealthReady | JSONResponse:
    report = await readiness_checker.check()
    failed_checks = report.failed_checks()
    if failed_checks:
        envelope = ErrorEnvelope(
            code="SERVICE_NOT_READY",
            message="서비스가 요청을 받을 준비가 되지 않았습니다.",
            fields={"failed_checks": failed_checks},
            request_id=uuid4(),
            retryable=True,
        )
        return JSONResponse(
            status_code=503,
            content=envelope.model_dump(mode="json"),
        )

    return HealthReady(checks=HealthChecks())
