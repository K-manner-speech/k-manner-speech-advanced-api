from pathlib import Path


def test_persona_prompt_bundle_key_is_explicit_and_validated() -> None:
    migration = Path(
        "supabase/migrations/20260828123000_add_persona_prompt_bundle_key.sql"
    ).read_text()

    assert "add column prompt_bundle_key text" in migration
    assert "personas_prompt_bundle_key_format" in migration
    assert "^[a-z0-9_-]+$" in migration
