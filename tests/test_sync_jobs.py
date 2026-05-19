import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.admin_db import AdminRepository
from app.models import DailySpendRecord
from app.models import CampaignPerformanceRecord
from app.sync_jobs import run_meta_daily_sync_job, run_meta_monthly_sync_job


class FakeMetaCampaignClient:
    def __init__(self, access_token, graph_api_version, timeout_seconds):
        self.access_token = access_token
        self.graph_api_version = graph_api_version
        self.timeout_seconds = timeout_seconds

    def fetch_account_daily_campaigns(self, account_id, report_date):
        return [
            CampaignPerformanceRecord(
                report_date=report_date,
                platform="meta",
                account_id=account_id,
                account_name="Meta Main",
                campaign_id="cmp-1",
                campaign_name="Campaign 1",
                currency="JPY",
                spend=Decimal("123"),
                impressions=100,
                clicks=5,
                conversions=Decimal("1"),
                timezone_name="Asia/Tokyo",
                fetched_at="2026-04-30T00:00:00+00:00",
            )
        ]


class FailingMetaCampaignClient:
    def __init__(self, access_token, graph_api_version, timeout_seconds):
        pass

    def fetch_account_daily_campaigns(self, account_id, report_date):
        raise RuntimeError("meta api failed")


class FakeCampaignSheetsClient:
    def __init__(self, service_account_file, spreadsheet_id, sheet_name, headers, row_key_factory):
        self.rows = []

    def ensure_header(self):
        return None

    def upsert_rows(self, keyed_rows):
        self.rows = list(keyed_rows)
        return (0, len(self.rows))


class FakeSheetManager:
    def __init__(self, service_account_file):
        pass

    def create_spreadsheet_in_folder(self, *, title, folder_id, initial_sheet_name):
        return {
            "spreadsheet_id": "sheet-job-1",
            "spreadsheet_title": title,
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet-job-1/edit",
        }


class FakeMetaDailyClient:
    def __init__(self, access_token, graph_api_version, timeout_seconds):
        self.access_token = access_token

    def fetch_account_daily_spend(self, account_id, report_date):
        return DailySpendRecord(
            report_date=report_date,
            account_id=account_id,
            account_name=f"Account {account_id}",
            currency="JPY",
            spend=Decimal("123.45"),
            timezone_name="Asia/Tokyo",
            fetched_at="2026-05-12T00:00:00+00:00",
        )


class FakeMetaDailySheetsClient:
    def __init__(self, service_account_file, spreadsheet_id, sheet_name):
        self.rows = []

    def ensure_header(self):
        return None

    def upsert_rows(self, keyed_rows):
        self.rows = list(keyed_rows)
        return (0, len(self.rows))


class SyncJobsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "fredcore.db"
        self.repository = AdminRepository(self.database_path)
        self.repository.initialize()
        self.repository.create_credential(
            platform="meta",
            profile_name="Meta OAuth",
            profile_identifier="meta@example.com",
            creator_email="test@example.com",
            auth_expiry="",
            auth_type="oauth",
            access_token="oauth-token-1",
        )
        credential_id = self.repository.list_credentials("meta", "Meta OAuth")[0]["id"]
        self.repository.create_account(
            platform="meta",
            account_name="Meta Main",
            account_identifier="act_123",
            timezone_name="Asia/Tokyo",
            credential_profile_id=credential_id,
            operator_email="test@example.com",
            parent_account="-",
        )
        self.settings = {
            "meta_access_token": "fallback-token",
            "meta_graph_api_version": "v22.0",
            "meta_request_timeout_seconds": "30",
            "google_service_account_file": "service.json",
            "google_spreadsheet_id": "sheet-daily-1",
            "google_sheet_name": "Meta Daily Spend",
            "google_reports_folder_id": "folder-123",
            "google_monthly_report_sheet_tab_name": "キャンペーン一覧",
            "report_timezone": "Asia/Tokyo",
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_meta_monthly_sync_job_records_success(self):
        job = run_meta_monthly_sync_job(
            self.repository,
            settings=self.settings,
            project_root=Path(self.temp_dir.name),
            report_date_input="2026-04-30",
            trigger_source="cron",
            meta_client_factory=FakeMetaCampaignClient,
            sheets_client_factory=FakeCampaignSheetsClient,
            sheet_manager_factory=FakeSheetManager,
        )
        self.assertEqual(job.result.row_count, 1)
        rows = self.repository.list_sync_runs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "成功")
        self.assertEqual(rows[0]["trigger_source"], "cron")

    def test_run_meta_daily_sync_job_uses_oauth_token_and_updates_account(self):
        report_date = date.today().isoformat()
        job = run_meta_daily_sync_job(
            self.repository,
            settings=self.settings,
            project_root=Path(self.temp_dir.name),
            report_date_input=report_date,
            trigger_source="cron",
            meta_client_factory=FakeMetaDailyClient,
            sheets_client_factory=FakeMetaDailySheetsClient,
        )
        self.assertEqual(job.result.row_count, 1)
        self.assertEqual(job.result.failure_count, 0)
        account = self.repository.list_accounts("meta")[0]
        self.assertEqual(account["sync_status"], "同期済み")
        self.assertEqual(account["last_synced_report_date"], report_date)
        rows = self.repository.list_sync_runs()
        self.assertEqual(rows[0]["job_name"], "meta_daily_spend_sync")
        self.assertEqual(rows[0]["status"], "成功")

    def test_run_meta_monthly_sync_job_records_failure(self):
        with self.assertRaises(RuntimeError):
            run_meta_monthly_sync_job(
                self.repository,
                settings=self.settings,
                project_root=Path(self.temp_dir.name),
                report_date_input="2026-04-30",
                trigger_source="cron",
                meta_client_factory=FailingMetaCampaignClient,
                sheets_client_factory=FakeCampaignSheetsClient,
                sheet_manager_factory=FakeSheetManager,
            )
        rows = self.repository.list_sync_runs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "失敗")
        self.assertIn("meta api failed", rows[0]["error_message"])


if __name__ == "__main__":
    unittest.main()
