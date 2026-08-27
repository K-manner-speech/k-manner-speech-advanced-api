"""Cross-check worker audio_type literals against the database CHECK constraint.

The worker once inserted message_audio.audio_type='tts' while the schema only
permitted 'user_recording' or 'persona_tts', so every TTS fan-out failed at
runtime. Parsing both sides keeps that mismatch from returning silently.

The constraint is read from the newest migration that redefines it, not from the
baseline alone, so a later migration that widens the allowed set stays authoritative.
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path("supabase/migrations")
ADAPTERS = Path("worker/domain_adapters.py")

CONSTRAINT = re.compile(
    r"audio_type\s*(?:=\s*ANY\s*\(ARRAY\[(?P<any>[^]]+)\]\)|in\s*\((?P<in>[^)]+)\))",
    re.IGNORECASE,
)


def allowed_audio_types() -> set[str]:
    """Return the effective allowed set from the newest migration that defines it."""
    for path in sorted(MIGRATIONS.glob("*.sql"), reverse=True):
        matches = CONSTRAINT.findall(path.read_text(encoding="utf-8"))
        if matches:
            any_form, in_form = matches[-1]
            return set(re.findall(r"'([^']+)'", any_form or in_form))
    raise AssertionError("no migration defines a message_audio audio_type constraint")


def test_worker_inserts_only_permitted_audio_types() -> None:
    allowed = allowed_audio_types()
    assert allowed, "audio_type constraint parsed as empty"

    source = ADAPTERS.read_text(encoding="utf-8")
    inserts = re.findall(
        r"insert into public\.message_audio\s*\((?P<columns>.*?)\)\s*"
        r"values \((?P<values>.*?)\)",
        source,
        re.DOTALL,
    )
    assert inserts, "no message_audio insert found in worker/domain_adapters.py"

    for columns, values in inserts:
        column_names = [name.strip() for name in columns.split(",")]
        assert "audio_type" in column_names, "message_audio insert must set audio_type"
        literal = [item.strip() for item in values.split(",")][column_names.index("audio_type")]
        assert literal.startswith("'") and literal.endswith("'"), (
            f"audio_type must be a literal the constraint can be checked against, got {literal}"
        )
        assert literal.strip("'") in allowed, (
            f"worker inserts audio_type={literal} which violates {sorted(allowed)}"
        )
