import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_SPEC = (ROOT / "docs" / "API명세.md").read_text(encoding="utf-8")
ERD = (ROOT / "docs" / "ERD.md").read_text(encoding="utf-8")
MIGRATIONS = "\n".join(
    path.read_text(encoding="utf-8")
    for path in sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
)


class ResolvedContractDecisions(unittest.TestCase):
    def assert_api(self, pattern: str):
        self.assertIsNotNone(
            re.search(pattern, API_SPEC, re.S | re.I),
            f"API contract missing pattern: {pattern}",
        )

    def test_emo_retry_001_explicit_emotion_retry_endpoint(self):
        self.assert_api(
            r"`message_emotion\.retry`\s*\|\s*"
            r"`POST /api/v1/messages/\{message_id\}/emotion/retry`.*?"
            r"`202 DomainJobAccepted`.*?401,404,409,429,503"
        )

    def test_emo_retry_002_reuses_target_and_rejects_stale_result(self):
        self.assert_api(
            r"감정 분석 재시도.*?기존 `message_emotion_analysis` 행.*?"
            r"새 Job.*?processing_token.*?늦은 결과.*?저장하지"
        )
        self.assertNotIn(
            "감정 결과는 `Message.emotion` 또는 `FeedbackResponse.emotions`로 조회하며 "
            "별도 write API는 없다.",
            API_SPEC,
        )

    def test_doc_ret_001_document_delete_preserves_completed_analysis(self):
        self.assert_api(
            r"`interview_document\.delete`.*?논리 삭제.*?"
            r"Storage 원본.*?vector.*?완료된 분석.*?보존"
        )
        self.assertNotRegex(
            API_SPEC,
            re.compile(r"interview_document\.delete.*?DB/vector/object 삭제", re.S),
        )

    def test_doc_ret_002_deleted_source_cannot_feed_new_analysis(self):
        self.assert_api(
            r"삭제된 (?:문서|원본).*?보존된 분석.*?"
            r"새 (?:분석|면접 구성).*?입력으로 사용하지.*?invalidated"
        )
        self.assert_api(r"삭제된 원본.*?(?:Storage path|signed URL).*?제공하지")

    def test_doc_ret_003_fk_restrict_and_account_cascade_are_explicit(self):
        erd_pattern = (
            r"면접 문서.*?논리 삭제.*?완료된 분석.*?보존.*?"
            r"회원 탈퇴.*?문서.*?분석.*?영구 삭제"
        )
        self.assertIsNotNone(
            re.search(erd_pattern, ERD, re.S),
            f"ERD contract missing pattern: {erd_pattern}",
        )
        self.assertRegex(
            MIGRATIONS,
            re.compile(
                r"interview_document_analyses_document_id_fkey.*?"
                r"references interview_documents\(id\) on delete restrict",
                re.S | re.I,
            ),
        )
        self.assertRegex(
            MIGRATIONS,
            re.compile(
                r"interview_document_analyses_user_id_fkey.*?"
                r"references auth\.users\(id\) on delete cascade",
                re.S | re.I,
            ),
        )

    def test_consent_seed_001_api_contract_fixes_two_required_test_policies(self):
        self.assert_api(
            r"로컬 MVP 테스트 약관 정책.*?"
            r"`terms`\s*\|\s*`v1`\s*\|\s*필수\s*\|\s*활성.*?"
            r"`privacy`\s*\|\s*`v1`\s*\|\s*필수\s*\|\s*활성"
        )

    def test_consent_seed_002_migration_idempotently_seeds_both_policies(self):
        self.assertRegex(
            MIGRATIONS,
            re.compile(
                r"insert into public\.consent_policies\s*"
                r"\(consent_type, policy_version, is_required, is_active\)\s*"
                r"values\s*"
                r"\('terms',\s*'v1',\s*true,\s*true\),\s*"
                r"\('privacy',\s*'v1',\s*true,\s*true\).*?"
                r"on conflict \(consent_type, policy_version\)\s*"
                r"do update set\s*"
                r"is_required\s*=\s*excluded\.is_required,\s*"
                r"is_active\s*=\s*excluded\.is_active",
                re.S | re.I,
            ),
        )
        self.assertNotRegex(
            MIGRATIONS,
            re.compile(r"effective_at\s*=\s*excluded\.effective_at", re.I),
        )


if __name__ == "__main__":
    unittest.main()
