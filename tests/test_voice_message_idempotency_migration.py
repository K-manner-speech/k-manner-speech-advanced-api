from pathlib import Path

MIGRATIONS = Path(__file__).parents[1] / "supabase" / "migrations"


def test_voice_message_scope_is_allowed_without_dropping_existing_scopes() -> None:
    migration = next(MIGRATIONS.glob("*_add_voice_message_idempotency_scope.sql"))
    migration_sql = migration.read_text()
    required_scopes = {
        "room.create",
        "room.delete",
        "room_message.create",
        "room_voice_message.create",
        "message_response.retry",
        "message_feedback.retry",
        "message_emotion.retry",
        "message_tts.retry",
        "message_repeat.create",
        "room_result.retry",
        "result.delete",
        "interview_setup.create",
        "interview_document.create",
        "interview_document.analyze",
        "interview_document.replace",
        "interview_document.delete",
        "interview_configuration.generate",
        "interview_configuration.regenerate",
        "interview_practice_room.create",
        "onboarding.complete",
        "account.delete",
    }

    assert all(f"'{scope}'::text" in migration_sql for scope in required_scopes)
    assert "drop constraint idempotency_records_action_scope_check" in migration_sql.lower()
