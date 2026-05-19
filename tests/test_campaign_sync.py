import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.admin_db import AdminRepository
from app.campaign_sync import sync_meta_campaigns_to_monthly_sheet
from app.models import CampaignPerformanceRecord


class FakeMetaCampaignClient:
    used_tokens = []

    def __init__(self, access_token, graph_api_version, timeout_seconds):
        self.access_token = access_token
        self.graph_api_version = graph_api_version
        self.timeout_seconds = timeout_seconds
        self.__class__.used_tokens.append(access_token)

    def fetch_account_daily_campaigns(self, account_id, report_date):
        return [
            CampaignPerformanceRecord(
                report_date=report_date,
                platform="meta",
                account_id=account_id,
                account_name=f"Account {account_id}",
                campaign_id="cmp-1",
                campaign_name="Campaign 1",
                currency="JPY",
                spend=Decimal("100"),
                impressions=1000,
                clicks=12,
                conversions=Decimal("2"),
                timezone_name="Asia/Tokyo",
                fetched_at="2026-04-30T00:00:00+00:00",
            ),
            CampaignPerformanceRecord(
                report_date=report_date,
                platform="meta",
                account_id=account_id,
                account_name=f"Account {account_id}",
                campaign_id="cmp-2",
                campaign_name="Campaign 2",
                currency="JPY",
                spend=Decimal("0"),
                impressions=0,
                clicks=0,
                conversions=Decimal("0"),
                timezone_name="Asia/Tokyo",
                fetched_at="2026-04-30T00:00:00+00:00",
            ),
        ]


class FakeCampaignSheetsClient:
    def __init__(self, service_account_file, spreadsheet_id, sheet_name, headers, row_key_factory):
        self.service_account_file = service_account_file
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.headers = headers
        self.row_key_factory = row_key_factory
        self.header_ensured = False
        self.rows = []

    def ensure_header(self):
        self.header_ensured = True

    def upsert_rows(self, keyed_rows):
        self.rows = list(keyed_rows)
        return (0, len(self.rows))

    def sort_rows(self):
        pass


class FakeSheetManager:
    def __init__(self, service_account_file):
        self.service_account_file = service_account_file

    def create_spreadsheet_in_folder(self, *, title, folder_id, initial_sheet_name):
        return {
            "spreadsheet_id": "monthly-sheet-1",
            "spreadsheet_title": title,
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/monthly-sheet-1/edit",
        }


class CampaignSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "fredcore.db"
        self.repository = AdminRepository(self.database_path)
        self.repository.initialize()
        FakeMetaCampaignClient.used_tokens = []
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

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sync_meta_campaigns_to_monthly_sheet(self):
        result = sync_meta_campaigns_to_monthly_sheet(
            self.repository.list_accounts("meta"),
            settings={
                "meta_access_token": "token",
                "meta_graph_api_version": "v22.0",
                "meta_request_timeout_seconds": "30",
                "google_service_account_file": "service.json",
                "google_reports_folder_id": "folder-123",
                "google_monthly_report_sheet_tab_name": "キャンペーン一覧",
                "report_timezone": "Asia/Tokyo",
            },
            project_root=Path(self.temp_dir.name),
            report_date_input="2026-04-30",
            meta_client_factory=FakeMetaCampaignClient,
            sheets_client_factory=FakeCampaignSheetsClient,
            sheet_manager_factory=FakeSheetManager,
            repository=self.repository,
        )
        self.assertEqual(result.report_date, "2026-04-30")
        self.assertEqual(result.month_key, "2026-04")
        self.assertEqual(result.account_count, 1)
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.appended_count, 1)
        self.assertTrue(result.created_spreadsheet)
        saved = self.repository.get_monthly_report_sheet("2026-04")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["spreadsheet_id"], "monthly-sheet-1")

    def test_sync_meta_campaigns_to_monthly_sheet_can_use_oauth_token_and_fixed_spreadsheet(self):
        result = sync_meta_campaigns_to_monthly_sheet(
            self.repository.list_accounts("meta"),
            settings={
                "meta_access_token": "",
                "meta_graph_api_version": "v22.0",
                "meta_request_timeout_seconds": "30",
                "google_service_account_file": "service.json",
                "google_spreadsheet_id": "fixed-sheet-1",
                "google_reports_folder_id": "",
                "google_monthly_report_sheet_tab_name": "キャンペーン一覧",
                "report_timezone": "Asia/Tokyo",
            },
            project_root=Path(self.temp_dir.name),
            report_date_input="2026-04-30",
            meta_client_factory=FakeMetaCampaignClient,
            sheets_client_factory=FakeCampaignSheetsClient,
            repository=self.repository,
        )
        self.assertEqual(result.spreadsheet_url, "https://docs.google.com/spreadsheets/d/fixed-sheet-1/edit")
        self.assertFalse(result.created_spreadsheet)
        self.assertEqual(FakeMetaCampaignClient.used_tokens, ["oauth-token-1"])
        self.assertIsNone(self.repository.get_monthly_report_sheet("2026-04"))


if __name__ == "__main__":
    unittest.main()
