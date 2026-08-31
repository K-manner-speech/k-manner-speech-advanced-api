from pathlib import Path


def test_interview_answers_completion_state_is_persisted() -> None:
    migration = Path(
        "supabase/migrations/20260828103500_add_interview_answer_completion.sql"
    ).read_text(encoding="utf-8")

    assert "is_current boolean" not in migration
    assert "comment on column public.interview_answers.is_current" in migration
    assert "AI가 현재 질문에 충분히 답했다고 판정" in migration
