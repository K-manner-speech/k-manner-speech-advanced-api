from pathlib import Path


def test_private_interview_documents_bucket_is_declared() -> None:
    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("supabase/migrations").glob("*.sql"))
    ).lower()

    assert "insert into storage.buckets" in migrations
    assert "'interview-documents'" in migrations
    assert "10485760" in migrations
    assert "false" in migrations
