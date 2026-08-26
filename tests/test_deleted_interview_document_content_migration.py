from pathlib import Path

MIGRATION = Path("supabase/migrations/20260826012400_scrub_deleted_interview_document_content.sql")


def test_deleted_interview_document_content_is_scrubbed_by_migration() -> None:
    sql = MIGRATION.read_text().lower()

    assert "update public.interview_documents" in sql
    assert "set extracted_content = '{}'::jsonb" in sql
    assert "where deleted_at is not null" in sql
    assert "is_current = true" not in sql
