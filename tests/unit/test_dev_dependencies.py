import importlib
from pathlib import Path


def test_remote_smoke_uses_official_httpx_dependency() -> None:
    root = Path(__file__).parents[2]
    requirements = (root / "requirements-dev.txt").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert "httpx==0.28.1" in requirements, "AC-T1-OFFICIAL-HTTPX"
    assert '"httpx==0.28.1"' in pyproject, "AC-T1-OFFICIAL-HTTPX"
    assert "httpx2" not in requirements
    assert "httpx2" not in pyproject
    assert importlib.import_module("scripts.remote_demo_smoke") is not None
