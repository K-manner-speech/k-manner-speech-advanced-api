from pathlib import Path

MIGRATIONS = Path(__file__).parents[1] / "supabase" / "migrations"


def test_conversation_text_timeout_is_extended_to_45_seconds() -> None:
    migration = next(MIGRATIONS.glob("*_extend_conversation_text_timeout.sql"))
    migration_sql = migration.read_text().lower()

    assert "update public.processing_timeout_policies" in migration_sql
    assert "timeout_seconds = 45" in migration_sql
    assert "job_type = 'conversation_text'" in migration_sql
