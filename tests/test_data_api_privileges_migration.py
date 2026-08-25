import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "supabase" / "migrations"


class DataApiPrivilegesMigrationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        matches = sorted(MIGRATION_DIR.glob("*_harden_data_api_privileges.sql"))
        if len(matches) != 1:
            raise AssertionError("expected exactly one harden_data_api_privileges migration")
        cls.sql = matches[0].read_text(encoding="utf-8").lower()

    def assert_sql(self, pattern: str):
        self.assertRegex(self.sql, re.compile(pattern, re.S | re.I))

    def test_future_migration_objects_are_opt_in(self):
        for object_type in ("tables", "sequences", "functions"):
            self.assert_sql(
                r"alter default privileges for role postgres in schema public\s+"
                rf"revoke all privileges on {object_type} from "
                r"public, anon, authenticated, service_role"
            )
        self.assertNotIn("for role supabase_admin", self.sql)

    def test_anon_and_public_have_no_data_api_object_privileges(self):
        self.assert_sql(
            r"revoke all privileges on all tables in schema public "
            r"from public, anon, authenticated"
        )
        self.assert_sql(
            r"revoke all privileges on all sequences in schema public "
            r"from public, anon, authenticated"
        )
        self.assertNotRegex(self.sql, re.compile(r"grant\s+.+?\s+to\s+anon\b", re.S))

    def test_internal_functions_are_not_directly_callable(self):
        self.assert_sql(
            r"revoke execute on all functions in schema public "
            r"from public, anon, authenticated"
        )
        self.assertNotRegex(
            self.sql,
            re.compile(r"grant\s+execute\s+.+?\s+to\s+authenticated\b", re.S),
        )

    def test_authenticated_catalog_and_job_access_is_read_only(self):
        read_only_block = re.search(
            r"grant select on table(?P<tables>.+?)to authenticated;",
            self.sql,
            re.S,
        )
        self.assertIsNotNone(read_only_block)
        tables = read_only_block.group("tables")
        for table in (
            "consent_policies",
            "persona_scenarios",
            "personas",
            "processing_jobs",
            "scenario_success_conditions",
            "scenarios",
            "storage_deletion_jobs",
        ):
            self.assertIn(f"public.{table}", tables)

    def test_authenticated_user_tables_only_receive_dml(self):
        self.assert_sql(r"grant select, insert, update, delete on table")
        for forbidden_privilege in (
            "maintain",
            "references",
            "trigger",
            "truncate",
        ):
            self.assertNotIn(f"grant {forbidden_privilege}", self.sql)

    def test_service_only_tables_are_not_granted_to_authenticated(self):
        grants = re.findall(
            r"grant\s+.+?\s+on table(?P<tables>.+?)to authenticated;",
            self.sql,
            re.S,
        )
        granted_tables = "\n".join(grants)
        self.assertNotIn("public.idempotency_records", granted_tables)
        self.assertNotIn("public.processing_timeout_policies", granted_tables)


if __name__ == "__main__":
    unittest.main()
