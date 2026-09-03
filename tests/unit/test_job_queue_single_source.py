from __future__ import annotations

import re
from pathlib import Path

from app.core.config import BASE_QUEUE_NAMES
from app.schemas.common import JobType
from app.services.jobs import (
    get_job_execution_policy,
    get_job_queue_name,
    get_job_target_column,
)
from worker.runtime import JOB_QUEUE_NAMES
from worker.sql_queue import TARGET_COLUMNS

REPOSITORIES = Path(__file__).parents[2] / "app" / "repositories"


def test_every_job_type_is_fully_registered() -> None:
    for job_type in JobType:
        assert get_job_queue_name(job_type) in BASE_QUEUE_NAMES
        assert get_job_target_column(job_type)
        assert get_job_execution_policy(job_type).deadline_seconds > 0


def test_worker_tables_are_derived_from_the_single_source() -> None:
    """발행과 소비가 다른 표를 보면 queue 를 옮길 때 job 이 붕 뜬다."""
    assert {job_type: get_job_queue_name(job_type) for job_type in JobType} == JOB_QUEUE_NAMES
    assert {job_type: get_job_target_column(job_type) for job_type in JobType} == TARGET_COLUMNS


def test_repositories_never_hardcode_a_queue_name() -> None:
    """enqueue 의 queue 는 job 유형에서 파생해야 한다.

    큐 재분배 때 worker 쪽 매핑만 고치고 API 쪽 enqueue 를 놓쳐, 재시도로 만든
    job 이 옛 queue 로 발행돼 아무도 집어가지 않은 적이 있다.
    """
    offenders: list[str] = []
    for path in sorted(REPOSITORIES.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        # 인자가 다음 줄로 넘어가는 호출도 잡아야 하므로 파일 전체를 본다.
        for match in re.finditer(r"\benqueue\(\s*[\"']", source):
            number = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.name}:{number}")

    assert not offenders, "queue 이름을 문자열로 넘긴 곳: " + "; ".join(offenders)
