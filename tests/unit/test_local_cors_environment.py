from __future__ import annotations

import json
from pathlib import Path


def test_environment_template_allows_only_vite_development_origins() -> None:
    template = Path(".env.example").read_text(encoding="utf-8").splitlines()
    raw_origins = next(
        line.split("=", 1)[1]
        for line in template
        if line.startswith("CORS_ALLOWED_ORIGINS=")
    )

    assert json.loads(raw_origins) == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
