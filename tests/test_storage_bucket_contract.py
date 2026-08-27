"""Every storage bucket the code writes to must be declared in a migration.

The TTS worker uploaded persona audio to 'message-audio' for weeks while no
migration ever created that bucket, so each TTS job failed with
STORAGE_UNAVAILABLE. Comparing referenced buckets against declared ones keeps a
missing bucket from shipping again.
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path("supabase/migrations")
SOURCE_DIRS = (Path("app"), Path("worker"))

# First string argument of the StorageObjectStore calls that take a bucket name,
# plus module-level bucket constants (interview-documents is passed as DOCUMENT_BUCKET).
BUCKET_CALL = re.compile(
    r"\.(?:upload|delete|create_signed_url)\(\s*[\"']([a-z0-9][a-z0-9-]*)[\"']",
)
BUCKET_CONSTANT = re.compile(r"^[A-Z_]*BUCKET[A-Z_]*\s*=\s*[\"']([a-z0-9][a-z0-9-]*)[\"']", re.M)


def declared_buckets() -> set[str]:
    sql = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(MIGRATIONS.glob("*.sql"))
    )
    inserts = re.findall(
        r"insert into storage\.buckets\s*\([^)]*\)\s*values\s*\(\s*'([^']+)'",
        sql,
        re.IGNORECASE,
    )
    return set(inserts)


def referenced_buckets() -> set[str]:
    names: set[str] = set()
    for directory in SOURCE_DIRS:
        for path in directory.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            names.update(BUCKET_CALL.findall(source))
            names.update(BUCKET_CONSTANT.findall(source))
    return names


def test_every_referenced_bucket_is_created_by_a_migration() -> None:
    referenced = referenced_buckets()
    assert referenced, "no storage bucket references found; the detection regex is stale"

    missing = referenced - declared_buckets()
    assert not missing, f"code writes to buckets no migration creates: {sorted(missing)}"


def test_message_audio_bucket_is_private_and_declared() -> None:
    assert "message-audio" in declared_buckets()

    sql = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(MIGRATIONS.glob("*.sql"))
    )
    block = re.search(
        r"insert into storage\.buckets.*?values\s*\(\s*'message-audio'.*?;",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert block is not None
    assert "false" in block.group(0), "message-audio must stay private; audio is signed on demand"
