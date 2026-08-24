import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "supabase" / "migrations"


class ScreenPlanDatabaseMigrationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sql = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(MIGRATION_DIR.glob("*.sql"))
        ).lower()

    def assert_sql(self, pattern: str):
        self.assertRegex(self.sql, re.compile(pattern, re.S | re.I))

    def test_db01_message_idempotency_and_sequence_uniqueness(self):
        self.assert_sql(r"add column if not exists client_request_id uuid")
        self.assert_sql(r"unique\s*\(room_id,\s*client_request_id\)")
        self.assert_sql(r"unique\s*\(room_id,\s*sequence_no\)")

    def test_db02_single_ai_reply_per_user_message(self):
        self.assert_sql(r"add column if not exists reply_to_message_id uuid")
        self.assert_sql(r"unique\s*\(reply_to_message_id\)")

    def test_db03_independent_processing_records(self):
        for table in ("message_ai_processing", "message_emotion_analysis"):
            self.assertIn(f"create table if not exists public.{table}", self.sql)
        self.assert_sql(r"processing_status.*check.*processing.*succeeded.*failed")

    def test_db04_emotion_enum_contract(self):
        for emotion in ("neutral", "happy", "sad", "angry", "curious", "embarrassment"):
            self.assertIn(f"'{emotion}'", self.sql)
        self.assertIn("reasoning", self.sql)

    def test_db05_score_integer_range_and_categories(self):
        self.assert_sql(r"score.*between 0 and 25")
        self.assert_sql(r"unique\s*\(feedback_id,\s*category\)")
        for category in ("honorifics", "courtesy", "context_fit", "naturalness"):
            self.assertIn(f"'{category}'", self.sql)

    def test_db06_scenario_success_conditions(self):
        self.assertIn("create table if not exists public.scenario_success_conditions", self.sql)
        self.assertIn("create table if not exists public.room_success_condition_progress", self.sql)

    def test_db07_interview_document_version_and_analysis(self):
        for column in ("version_no", "is_current", "upload_status", "analysis_status", "deleted_at"):
            self.assertIn(column, self.sql)
        self.assertIn("create table if not exists public.interview_document_analyses", self.sql)

    def test_db08_results_are_independent_snapshots(self):
        self.assert_sql(r"alter table public.session_results\s+add column if not exists user_id uuid")
        self.assertIn("source_snapshot", self.sql)
        self.assertIn("on delete set null", self.sql)

    def test_db08_room_reference_is_nullable_after_room_deletion(self):
        self.assert_sql(r"alter table public.session_results\s+alter column room_id drop not null")

    def test_db08_result_rls_uses_snapshot_owner(self):
        self.assertIn("drop policy if exists session_results_own_room", self.sql)
        self.assert_sql(r"create policy session_results_own_user.*user_id\s*=\s*auth\.uid\(\)")
        self.assertIn("drop policy if exists result_items_own_result", self.sql)
        self.assertIn("create policy result_items_own_user_result", self.sql)

    def test_db09_rls_is_enabled_for_new_user_tables(self):
        for table in (
            "message_ai_processing",
            "message_emotion_analysis",
            "scenario_success_conditions",
            "room_success_condition_progress",
            "interview_document_analyses",
            "room_contexts",
            "storage_deletion_jobs",
        ):
            self.assertIn(f"alter table public.{table} enable row level security", self.sql)

    def test_db10_storage_deletion_queue(self):
        self.assertIn("create table if not exists public.storage_deletion_jobs", self.sql)
        self.assertIn("storage_path", self.sql)
        self.assertIn("attempt_count", self.sql)

    def test_db11_private_room_context(self):
        self.assertIn("create table if not exists public.room_contexts", self.sql)
        self.assertIn("summary_text", self.sql)
        self.assertIn("summarized_through_message_id", self.sql)

    def test_db12_query_indexes(self):
        for index in (
            "practice_rooms_user_updated_idx",
            "room_messages_room_sequence_idx",
            "session_results_user_created_idx",
            "storage_deletion_jobs_status_created_idx",
        ):
            self.assertIn(index, self.sql)


if __name__ == "__main__":
    unittest.main()
