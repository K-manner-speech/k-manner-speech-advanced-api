from pathlib import Path


def test_worker_heartbeat_and_required_queues_are_migrated_privately() -> None:
    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("supabase/migrations").glob("*.sql"))
    ).lower()

    assert "create table public.worker_heartbeats" in migrations
    assert "enable row level security" in migrations
    assert "revoke all on table public.worker_heartbeats from anon, authenticated" in migrations
    for queue_name in (
        "conversation_text",
        "conversation_text_dlq",
        "interactive_ai",
        "interactive_ai_dlq",
        "document_analysis",
        "document_analysis_dlq",
    ):
        assert f"pgmq.create('{queue_name}')" in migrations


def test_worker_heartbeat_table_has_queue_freshness_key() -> None:
    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("supabase/migrations").glob("*.sql"))
    ).lower()

    assert "primary key (worker_id, queue_name)" in migrations
    assert "last_seen_at timestamp with time zone" in migrations


def test_required_vector_extension_is_declared() -> None:
    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("supabase/migrations").glob("*.sql"))
    ).lower()

    assert "create extension if not exists vector" in migrations
