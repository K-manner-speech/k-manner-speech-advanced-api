import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "supabase" / "migrations"


class ScreenPlanDatabaseMigrationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration_paths = sorted(MIGRATION_DIR.glob("*.sql"))
        cls.sql = "\n".join(
            path.read_text(encoding="utf-8") for path in cls.migration_paths
        ).lower()
        cls.latest_sql = cls.migration_paths[-1].read_text(encoding="utf-8").lower()

    def assert_sql(self, pattern: str):
        self.assertRegex(self.sql, re.compile(pattern, re.S | re.I))

    def test_db01_message_idempotency_and_sequence_uniqueness(self):
        self.assertIn("client_request_id uuid", self.sql)
        self.assert_sql(r"unique\s*\(room_id,\s*client_request_id\)")
        self.assert_sql(r"unique\s*\(room_id,\s*sequence_no\)")

    def test_db02_single_ai_reply_per_user_message(self):
        self.assertIn("reply_to_message_id uuid", self.sql)
        self.assert_sql(r"unique\s*\(reply_to_message_id\)")

    def test_db03_independent_processing_records(self):
        for table in ("message_ai_processing", "message_emotion_analysis"):
            self.assert_sql(rf"create table(?: if not exists)? public\.{table}")
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
        self.assertNotRegex(
            self.latest_sql,
            re.compile(r"category in\s*\([^)]*'consideration'", re.S),
        )

    def test_db06_scenario_success_conditions(self):
        self.assert_sql(r"create table(?: if not exists)? public\.scenario_success_conditions")
        self.assert_sql(r"create table(?: if not exists)? public\.room_success_condition_progress")

    def test_db07_interview_document_version_and_analysis(self):
        for column in (
            "version_no",
            "is_current",
            "upload_status",
            "analysis_status",
            "deleted_at",
        ):
            self.assertIn(column, self.sql)
        self.assert_sql(r"create table(?: if not exists)? public\.interview_document_analyses")

    def test_db08_results_are_independent_snapshots(self):
        self.assert_sql(r"create table public\.session_results.*user_id uuid not null")
        self.assertIn("source_snapshot", self.sql)
        self.assertIn("on delete set null", self.sql)

    def test_db08_room_reference_is_nullable_after_room_deletion(self):
        self.assert_sql(r"create table public\.session_results\s*\(.*room_id uuid,")

    def test_db08_result_rls_uses_snapshot_owner(self):
        self.assert_sql(r"create policy session_results_own_user.*user_id\s*=\s*auth\.uid\(\)")
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
        self.assert_sql(r"create table(?: if not exists)? public\.storage_deletion_jobs")
        self.assertIn("storage_path", self.sql)
        self.assertIn("attempt_count", self.sql)

    def test_db11_private_room_context(self):
        self.assert_sql(r"create table(?: if not exists)? public\.room_contexts")
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

    def test_p3_interview_configuration_question_answer_model(self):
        for table in (
            "interview_configurations",
            "interview_questions",
            "interview_answers",
        ):
            self.assert_sql(rf"create table(?: if not exists)? public\.{table}")
        self.assert_sql(r"unique\s*\(setup_id,\s*version_no\)")
        self.assert_sql(r"unique\s*\(setup_id,\s*idempotency_key\)")
        self.assert_sql(r"unique\s*\(configuration_id,\s*sequence_no\)")
        self.assertIn("interview_answers_one_current_idx", self.sql)
        self.assertIn("synchronize_interview_question_count", self.sql)

    def test_p3_interview_model_has_rls(self):
        for table in (
            "interview_configurations",
            "interview_questions",
            "interview_answers",
        ):
            self.assertIn(f"alter table public.{table} enable row level security", self.sql)
        self.assertIn("interview_configurations_own_all", self.sql)
        self.assertIn("interview_questions_own_configuration", self.sql)
        self.assertIn("interview_answers_own_configuration", self.sql)

    def test_p4_score_sum_trigger_and_emotion_limits(self):
        self.assertIn("recalculate_turn_feedback_overall_score", self.sql)
        self.assertIn("feedback_scores_recalculate_overall_trigger", self.sql)
        self.assertIn("validate_feedback_emotion_limit", self.sql)
        self.assert_sql(r"percentage.*>=\s*0.*percentage.*<=\s*100")
        self.assert_sql(r"sort_order.*>=\s*1.*sort_order.*<=\s*3")
        self.assert_sql(r"unique\s*\(feedback_id,\s*emotion_label\)")

    def test_p4_profile_and_required_consent_contract(self):
        self.assert_sql(r"create table(?: if not exists)? public\.consent_policies")
        self.assertIn("validate_profile_onboarding_completion", self.sql)
        self.assertIn("btrim(display_name)", self.sql)
        self.assertIn("birth_date <= current_date", self.sql)
        self.assert_sql(r"display_language.*'ko'.*'en'")

    def test_p5_partial_unique_room_indexes(self):
        for index in (
            "practice_rooms_one_active_free_chat_idx",
            "practice_rooms_one_active_scenario_idx",
            "practice_rooms_one_active_interview_idx",
        ):
            self.assertIn(index, self.sql)
        self.assertIn("interview_configuration_id", self.sql)

    def test_p6_deletion_queue_lock_and_retry_contract(self):
        for column in (
            "next_attempt_at",
            "locked_at",
            "locked_by",
            "lock_expires_at",
            "max_attempts",
        ):
            self.assertIn(column, self.sql)
        self.assertIn("storage_deletion_jobs_claim_idx", self.sql)

    def test_p6_processing_timeout_contract(self):
        self.assert_sql(r"create table(?: if not exists)? public\.processing_timeout_policies")
        for column in ("processing_token", "deadline_at", "next_attempt_at"):
            self.assertIn(column, self.sql)
        for index in (
            "message_ai_processing_timeout_idx",
            "message_emotion_analysis_timeout_idx",
            "message_audio_timeout_idx",
            "turn_feedback_timeout_idx",
            "interview_document_analyses_timeout_idx",
            "interview_configurations_timeout_idx",
        ):
            self.assertIn(index, self.sql)


if __name__ == "__main__":
    unittest.main()
