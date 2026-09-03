from __future__ import annotations

import inspect
import re
from pathlib import Path

from app.ai.prompts.policies.conversation import build_conversation_instructions
from worker.executors import WorkerExecutors

MIGRATIONS = Path(__file__).parents[2] / "supabase" / "migrations"


def _instructions(*, interview: bool = False, scenario: bool = False) -> str:
    return build_conversation_instructions(
        is_interview=interview, is_closing_response=False, is_scenario=scenario
    )


def test_scenario_persona_is_told_not_to_do_the_users_practice() -> None:
    """페르소나가 사용자보다 먼저 용건을 꺼내면 연습할 것이 사라진다."""
    scenario = _instructions(scenario=True)

    assert "scenario_goal" in scenario
    assert "먼저 알려주거나" in scenario
    # 이미 물어본 뒤에도 미루면 대화가 어색해진다.
    assert "이미 물었거나 요청했다면" in scenario


def test_restraint_rule_applies_only_to_scenarios() -> None:
    marker = "scenario_goal 은 사용자가 연습할 목표"

    assert marker not in _instructions()
    assert marker not in _instructions(interview=True)


def test_executor_passes_the_practice_type_through() -> None:
    source = inspect.getsource(WorkerExecutors._conversation)

    assert "is_scenario=" in source
    assert 'practice_type") == "scenario"' in source


def test_cafeteria_opening_leaves_the_first_move_to_the_user() -> None:
    """오프닝이 질문이면 사용자는 답변자가 되어 인사와 질문을 놓친다."""
    openings = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        if "20000000-0000-4000-8000-000000000003" not in text:
            continue
        openings += re.findall(r"opening_message\s*=\s*'([^']+)'", text)
        openings += re.findall(r"'(어[?,][^']*)'", text)

    assert openings, "식당 시나리오의 opening_message 를 찾지 못했다"
    for opening in openings:
        assert "어디 가는 길이야" not in opening
        assert "?" not in opening.rstrip("!").replace("어?", "")
