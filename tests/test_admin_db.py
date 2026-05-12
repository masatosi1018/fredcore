import tempfile
import unittest
from pathlib import Path

from app.admin_db import AdminRepository


class AdminRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "adasi.db"
        self.repository = AdminRepository(self.database_path)
        self.repository.initialize()
        self.repository.seed_if_empty()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seed_creates_platform_counts(self):
        counts = self.repository.get_platform_counts("credential_profiles")
        self.assertGreaterEqual(counts["google"], 1)
        self.assertGreaterEqual(counts["meta"], 1)
        self.assertGreaterEqual(counts["tiktok"], 1)

    def test_create_account_is_listed(self):
        credential_id = self.repository.credential_choices("google")[0]["id"]
        self.repository.create_account(
            platform="google",
            account_name="新規アカウント",
            account_identifier="9999999999",
            timezone_name="Asia/Tokyo",
            credential_profile_id=credential_id,
            operator_email="test@example.com",
            parent_account="-",
        )
        rows = self.repository.list_accounts("google", "新規")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account_identifier"], "9999999999")
        self.assertEqual(rows[0]["sync_status"], "未同期")
        self.assertEqual(rows[0]["selection_source"], "manual")

    def test_reauth_updates_status(self):
        credential = self.repository.list_credentials("google")[0]
        self.repository.reauth_credential(credential["id"])
        refreshed = self.repository.list_credentials("google")[0]
        self.assertEqual(refreshed["status"], "正常")

    def test_save_and_load_integration_settings(self):
        self.repository.save_integration_settings(
            {
                "meta_access_token": "token-123",
                "google_spreadsheet_id": "sheet-abc",
            }
        )
        settings = self.repository.get_integration_settings()
        self.assertEqual(settings["meta_access_token"], "token-123")
        self.assertEqual(settings["google_spreadsheet_id"], "sheet-abc")

    def test_save_monthly_report_sheet_extracts_spreadsheet_id(self):
        self.repository.save_monthly_report_sheet(
            month_key="2026-04",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/sheet-123456/edit#gid=0",
            spreadsheet_title="2026年4月 広告消化キャンペーン一覧",
            status="有効",
            notes="4月分",
        )
        rows = self.repository.list_monthly_report_sheets()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["month_key"], "2026-04")
        self.assertEqual(rows[0]["spreadsheet_id"], "sheet-123456")

    def test_save_monthly_report_sheet_updates_existing_month(self):
        self.repository.save_monthly_report_sheet(
            month_key="2026-05",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/sheet-old/edit#gid=0",
            spreadsheet_title="旧タイトル",
        )
        self.repository.save_monthly_report_sheet(
            month_key="2026-05",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/sheet-new/edit#gid=0",
            spreadsheet_title="新タイトル",
            status="停止中",
            notes="差し替え済み",
        )
        rows = self.repository.list_monthly_report_sheets()
        matching = [row for row in rows if row["month_key"] == "2026-05"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["spreadsheet_id"], "sheet-new")
        self.assertEqual(matching[0]["spreadsheet_title"], "新タイトル")
        self.assertEqual(matching[0]["status"], "停止中")

    def test_create_and_complete_sync_run(self):
        sync_run_id = self.repository.create_sync_run(
            job_name="meta_monthly_campaign_sync",
            platform="meta",
            trigger_source="manual",
            report_date="2026-04-30",
            month_key="2026-04",
        )
        self.repository.complete_sync_run(
            sync_run_id,
            status="成功",
            account_count=2,
            row_count=10,
            updated_count=3,
            appended_count=7,
            spreadsheet_url="https://docs.google.com/spreadsheets/d/sheet-1/edit",
            spreadsheet_title="2026年4月 広告消化キャンペーン一覧",
        )
        rows = self.repository.list_sync_runs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "成功")
        self.assertEqual(rows[0]["row_count"], 10)
        self.assertEqual(rows[0]["spreadsheet_title"], "2026年4月 広告消化キャンペーン一覧")

    def test_update_account_sync_state(self):
        account_id = self.repository.list_accounts("meta")[0]["id"]
        self.repository.update_account_sync_state(
            account_id,
            sync_status="同期済み",
            last_synced_at="2026-05-12T00:00:00+00:00",
            last_synced_report_date="2026-05-11",
        )
        row = self.repository.list_accounts("meta")[0]
        self.assertEqual(row["sync_status"], "同期済み")
        self.assertEqual(row["last_synced_report_date"], "2026-05-11")

    def test_create_and_consume_oauth_state(self):
        self.repository.create_oauth_state(
            state="state-123",
            platform="google",
            auth_type="oauth",
            payload_json='{"profile_name":"Google OAuth"}',
            code_verifier="verifier-123",
            expires_at="2026-05-01T00:00:00+00:00",
        )
        row = self.repository.consume_oauth_state("state-123")
        self.assertIsNotNone(row)
        self.assertEqual(row["platform"], "google")
        self.assertEqual(row["code_verifier"], "verifier-123")
        self.assertIsNone(self.repository.consume_oauth_state("state-123"))

if __name__ == "__main__":
    unittest.main()
