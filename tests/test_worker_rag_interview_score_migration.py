from pathlib import Path

MIGRATION = Path(
    "supabase/migrations/20260826024519_add_worker_rag_and_interview_scores.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_migration_creates_owner_version_scoped_vector_chunks() -> None:
    sql = migration_sql()

    assert "create table public.document_chunks" in sql
    assert "embedding extensions.vector(3072)" in sql
    assert (
        "(embedding::extensions.halfvec(3072)) extensions.halfvec_cosine_ops" in sql
    )
    assert "user_id uuid not null" in sql
    assert "document_id uuid not null" in sql
    assert "document_version integer not null" in sql
    assert "on delete cascade" in sql
    assert "enable row level security" in sql
    assert "revoke all on table public.document_chunks from anon, authenticated" in sql


def test_migration_creates_fixed_interview_evaluation_scores() -> None:
    sql = migration_sql()

    assert "create table public.interview_evaluation_scores" in sql
    for category in (
        "question_understanding_fit",
        "answer_structure",
        "specificity_evidence",
        "job_fit_problem_solving",
        "delivery_attitude",
    ):
        assert category in sql
    assert "score between 1 and 20" in sql
    assert "unique (result_id, category)" in sql
    assert "revoke all on table public.interview_evaluation_scores from anon, authenticated" in sql


def test_session_result_total_constraint_matches_partial_contract() -> None:
    sql = migration_sql()

    assert "session_results_interview_score_contract" in sql
    assert "overall_score between 5 and 100" in sql
    assert "overall_score is null" in sql
    assert "missing_categories" in sql
