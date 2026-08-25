from typing import Literal

from app.schemas.base import ContractModel


class HealthLive(ContractModel):
    status: Literal["ok"] = "ok"


class HealthChecks(ContractModel):
    database: Literal["ok"] = "ok"
    pgmq_queues: Literal["ok"] = "ok"
    required_extensions: Literal["ok"] = "ok"
    timeout_policies: Literal["ok"] = "ok"
    config: Literal["ok"] = "ok"
    worker_heartbeat: Literal["ok"] = "ok"


class HealthReady(ContractModel):
    status: Literal["ready"] = "ready"
    checks: HealthChecks
