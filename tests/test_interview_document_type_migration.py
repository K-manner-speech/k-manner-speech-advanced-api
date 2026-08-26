from pathlib import Path


def test_interview_document_type_matches_public_api() -> None:
    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("supabase/migrations").glob("*.sql"))
    ).lower()

    latest_contract = migrations.rsplit("interview_documents_type_check", maxsplit=1)[-1]
    assert "'resume'::text" in latest_contract
    assert "'portfolio'::text" in latest_contract
    assert "'self_introduction'::text" in latest_contract
    assert "'cover_letter'::text" not in latest_contract
