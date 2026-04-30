import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.admin_db import AdminRepository
from app.models import CampaignPerformanceRecord
from app.sync_jobs import run_meta_monthly_sync_job


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


class SyncJobsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "fredcore.db"
        self.repository = AdminRepository(self.database_path)
        self.repository.initialize()
        self.repository.create_account(
            platform="meta",
            account_name="Meta Main",
            account_identifier="act_123",
            timezone_name="Asia/Tokyo",
            credential_profile_id=None,
            operator_email="test@example.com",
            parent_account="-",
        )
        self.settings = {
            "meta_access_token": "token",
            "meta_graph_api_version": "v22.0",
            "meta_request_timeout_seconds": "30",
            "google_service_account_file": "service.json",
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
