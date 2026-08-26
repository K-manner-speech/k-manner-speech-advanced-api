from pathlib import Path

MIGRATIONS = Path(__file__).parents[1] / "supabase" / "migrations"


def test_only_one_active_account_deletion_is_allowed_per_user() -> None:
    migration = next(MIGRATIONS.glob("*_account_deletion_concurrency.sql"))
    sql = migration.read_text().lower()

    assert "unique index" in sql
    assert "idempotency_records" in sql
    assert "user_id" in sql
    assert "action_scope = 'account.delete'" in sql
    assert "state = 'in_progress'" in sql
