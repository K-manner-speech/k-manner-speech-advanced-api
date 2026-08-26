from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest


def load_breaker() -> ModuleType:
    path = Path(".agents/skills/plan-acc/breaker.py")
    spec = importlib.util.spec_from_file_location("plan_acc_breaker", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_verify_markdown_inline_code_is_not_executed_as_command_substitution() -> None:
    breaker = load_breaker()
    plan = """
### T1: Windows verify
- **AC:**
  - Given Windows, When 검증하면, Then 명령을 실행한다.
  - **Verify:** `python -m pytest tests/test_sample.py -q`
  - **Breaker:** `app/sample.py` :: `true` -> `false`
  - **Expect-red:** AC-T1-WINDOWS-VERIFY
  - **Observed:** 미관찰
"""

    block = breaker.parse_plan(plan)[0]

    assert block.verify == "python -m pytest tests/test_sample.py -q"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell routing is Windows-specific")
def test_windows_powershell_environment_syntax_uses_powershell() -> None:
    breaker = load_breaker()

    argv = breaker.command_argv("$env:PLAN_ACC_WINDOWS='ok'; Write-Output $env:PLAN_ACC_WINDOWS")

    assert Path(argv[0]).name.lower() in {"pwsh.exe", "powershell.exe"}
    assert "-NoProfile" in argv


@pytest.mark.skipif(os.name != "nt", reason="PowerShell execution is Windows-specific")
def test_windows_powershell_verify_command_executes(tmp_path: Path) -> None:
    breaker = load_breaker()

    output, exit_code, timed_out, limit_hit = breaker.run_command(
        "$env:PLAN_ACC_WINDOWS='ok'; Write-Output $env:PLAN_ACC_WINDOWS",
        tmp_path,
        os.environ.copy(),
    )

    assert exit_code == 0
    assert output == "ok\n"
    assert timed_out is False
    assert limit_hit is False


@pytest.mark.skipif(os.name != "nt", reason="Windows drive paths are Windows-specific")
def test_windows_drive_path_command_uses_powershell() -> None:
    breaker = load_breaker()

    argv = breaker.command_argv(r"C:\Python311\python.exe -m pytest -q")

    assert Path(argv[0]).name.lower() in {"pwsh.exe", "powershell.exe"}
