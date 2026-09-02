from __future__ import annotations

import inspect
import re
from typing import Any
from uuid import UUID, uuid4

from app.ai.schemas import ScenarioGoalCondition, ScenarioGoalProgress
from app.core.readiness import DatabaseReadinessChecker
from app.schemas.common import JobType
from app.services.jobs import get_job_execution_policy
from worker.domain_adapters import ConversationAdapter, GoalProgressAdapter
from worker.queue import ClaimedJob
from worker.runtime import JOB_QUEUE_NAMES
from worker.sql_queue import TARGET_COLUMNS, TARGET_STATE


class Recorder:
    """실행된 SQL과 파라미터를 모아두는 최소 Session 대역."""

    def __init__(self, scalars: list[Any], rows: list[Any]) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self._scalars = iter(scalars)
        self._rows = iter(rows)

    def execute(self, statement: Any, parameters: Any = None) -> Any:
        self.statements.append((str(statement), dict(parameters or {})))
        return _Result(self._scalars, self._rows)

    def sql_containing(self, needle: str) -> list[tuple[str, dict[str, Any]]]:
        return [entry for entry in self.statements if needle in entry[0]]


class _Result:
    def __init__(self, scalars: Any, rows: Any) -> None:
        self._scalars = scalars
        self._rows = rows

    def mappings(self) -> Any:
        return self

    def one_or_none(self) -> Any:
        return next(self._rows)

    def first(self) -> Any:
        return next(self._rows)

    def scalar_one(self) -> Any:
        return next(self._scalars)

    def scalar(self) -> Any:
        return next(self._scalars)


def _claimed(target_id: UUID, token: UUID) -> ClaimedJob:
    return ClaimedJob(
        job_id=uuid4(),
        job_type=JobType.SCENARIO_GOAL_PROGRESS,
        user_id=uuid4(),
        target_id=target_id,
        processing_token=token,
        attempt_count=1,
        schema_repair_count=0,
        deadline_at=None,
        payload={},
    )


def test_all_required_conditions_met_flags_the_room_without_completing_it() -> None:
    target_id, token, room_id = uuid4(), uuid4(), uuid4()
    session = Recorder(
        scalars=[0],  # 남은 필수 조건 0개
        rows=[{"room_id": room_id, "scenario_id": uuid4()}],
    )
    output = ScenarioGoalProgress(
        conditions=[
            ScenarioGoalCondition(
                condition_key="polite_greeting",
                achieved=True,
                evidence_sequence_no=2,
                reasoning="존댓말로 인사했습니다.",
            )
        ]
    )

    assert GoalProgressAdapter().complete(session, _claimed(target_id, token), output) is True

    flagged = session.sql_containing("ended_reason = 'goal_achieved'")
    assert len(flagged) == 1
    # 방을 끝내는 것은 사용자의 몫이다. 판정 잡은 표시만 남긴다.
    assert not session.sql_containing("status = 'completed'")
    assert not session.sql_containing("session_results")


def test_unmet_required_condition_leaves_the_room_untouched() -> None:
    session = Recorder(
        scalars=[2],  # 필수 조건 2개가 아직 미달
        rows=[{"room_id": uuid4(), "scenario_id": uuid4()}],
    )
    output = ScenarioGoalProgress(
        conditions=[
            ScenarioGoalCondition(
                condition_key="polite_greeting",
                achieved=True,
                evidence_sequence_no=2,
                reasoning=None,
            )
        ]
    )

    GoalProgressAdapter().complete(session, _claimed(uuid4(), uuid4()), output)

    assert not session.sql_containing("ended_reason = 'goal_achieved'")


def test_unachieved_conditions_never_write_progress_rows() -> None:
    """늦게 끝난 판정이 이미 달성된 조건을 되돌리면 안 된다."""
    session = Recorder(scalars=[1], rows=[{"room_id": uuid4(), "scenario_id": uuid4()}])
    output = ScenarioGoalProgress(
        conditions=[
            ScenarioGoalCondition(
                condition_key="gratitude",
                achieved=False,
                evidence_sequence_no=None,
                reasoning="감사 표현이 없습니다.",
            )
        ]
    )

    GoalProgressAdapter().complete(session, _claimed(uuid4(), uuid4()), output)

    assert not session.sql_containing("insert into public.room_success_condition_progress")


def test_progress_upsert_only_moves_false_to_true() -> None:
    source = inspect.getsource(GoalProgressAdapter.complete)

    assert "on conflict (room_id, condition_id) do update" in source
    assert "where not public.room_success_condition_progress.achieved" in source


def test_achievement_without_evidence_is_downgraded() -> None:
    condition = ScenarioGoalCondition(
        condition_key="clear_question",
        achieved=True,
        evidence_sequence_no=None,
        reasoning="물어본 것 같습니다.",
    )

    assert condition.achieved is False


def test_goal_progress_is_enqueued_only_for_scenarios_from_the_second_turn() -> None:
    source = inspect.getsource(ConversationAdapter._enqueue_goal_progress)

    assert "if turn_count < 2:" in source
    assert "r.practice_type = 'scenario'" in source
    assert "r.goal_prompt_dismissed_at is null" in source
    assert "job_type=JobType.SCENARIO_GOAL_PROGRESS" in source


def test_goal_progress_does_not_run_when_the_turn_already_completed_the_room() -> None:
    source = inspect.getsource(ConversationAdapter.complete)
    branches = re.findall(r"elif [^:]+:", source)

    assert any("_should_complete" in branch for branch in branches)
    assert 'elif target["practice_type"] == "scenario":' in source


def test_goal_progress_job_is_wired_into_the_evaluation_queue() -> None:
    assert JOB_QUEUE_NAMES[JobType.SCENARIO_GOAL_PROGRESS] == "evaluation_ai"
    assert TARGET_COLUMNS[JobType.SCENARIO_GOAL_PROGRESS] == "room_goal_evaluation_id"
    assert TARGET_STATE[JobType.SCENARIO_GOAL_PROGRESS] == (
        "room_goal_evaluations",
        "evaluation_status",
        True,
    )
    assert get_job_execution_policy(JobType.SCENARIO_GOAL_PROGRESS).deadline_seconds == 20


def test_scoring_jobs_moved_off_the_realtime_queue() -> None:
    """TTS는 사용자가 기다리는 작업이라 180초짜리 종합 결과와 분리한다."""
    assert JOB_QUEUE_NAMES[JobType.TTS_GENERATION] == "interactive_ai"
    assert JOB_QUEUE_NAMES[JobType.EMOTION_ANALYSIS] == "interactive_ai"
    assert JOB_QUEUE_NAMES[JobType.TURN_FEEDBACK] == "evaluation_ai"
    assert JOB_QUEUE_NAMES[JobType.SESSION_RESULT_GENERATION] == "evaluation_ai"


def test_readiness_counts_every_registered_job_type() -> None:
    """기대 개수만 고치고 조회 목록을 두면 readiness 가 영원히 통과하지 못한다."""
    source = inspect.getsource(DatabaseReadinessChecker.check)

    assert "policy_count == len(JobType)" in source
    # 세는 대상도 JobType 에서 파생돼야 한다. 목록이 하드코딩되면 잡을 늘려도
    # count 가 따라 오르지 않아 timeout_policies 가 계속 false 가 된다.
    assert "[job_type.value for job_type in JobType]" in source
    assert '"session_result_generation",' not in source
