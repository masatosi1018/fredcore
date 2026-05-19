import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from app.meta_sync import MetaSheetSyncConfig, merged_integration_settings, sync_meta_accounts_to_sheet
from app.models import DailySpendRecord


class FakeMetaClient:
    def __init__(self, access_token, graph_api_version, timeout_seconds):
        self.access_token = access_token
        self.graph_api_version = graph_api_version
        self.timeout_seconds = timeout_seconds

    def fetch_account_daily_spend(self, account_id, report_date):
        return DailySpendRecord(
            report_date=report_date,
            account_id=account_id,
            account_name=f"Account {account_id}",
            currency="JPY",
            spend=Decimal("123.45"),
            timezone_name="Asia/Tokyo",
            fetched_at="2026-04-23T00:00:00+00:00",
        )


class FakeSheetsClient:
    def __init__(self, service_account_file, spreadsheet_id, sheet_name):
        self.service_account_file = service_account_file
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.header_ensured = False
        self.rows = []

    def ensure_header(self):
        self.header_ensured = True

    def upsert_rows(self, keyed_rows):
        self.rows = list(keyed_rows)
        return (1, max(len(self.rows) - 1, 0))


class MetaSyncTest(unittest.TestCase):
    def test_sync_uses_registered_meta_accounts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = MetaSheetSyncConfig.from_mapping(
                {
                    "meta_access_token": "token",
                    "google_spreadsheet_id": "sheet-id",
                    "google_service_account_file": "service.json",
                },
                project_root=Path(temp_dir),
            )

            result = sync_meta_accounts_to_sheet(
                [
                    {"account_identifier": "act_123"},
                    {"account_identifier": "456"},
                ],
                config=config,
                report_date_input="2026-04-22",
                meta_client_factory=FakeMetaClient,
                sheets_client_factory=FakeSheetsClient,
            )

            self.assertEqual(result.report_date, "2026-04-22")
            self.assertEqual(result.account_count, 2)
            self.assertEqual(result.row_count, 2)
            self.assertEqual(result.updated_count, 1)
            self.assertEqual(result.appended_count, 1)

    def test_merged_integration_settings_keeps_defaults(self):
        merged = merged_integration_settings({"meta_access_token": "abc"})
        self.assertEqual(merged["meta_access_token"], "abc")
        self.assertEqual(merged["google_sheet_name"], "Meta Daily Spend")

    def test_merged_integration_settings_prefers_environment_values(self):
        with patch.dict(
            "os.environ",
            {
                "META_APP_ID": "env-app-id",
                "FREDCORE_APP_BASE_URL": "https://fredcore.vercel.app",
            },
            clear=False,
        ):
            merged = merged_integration_settings(
                {
                    "meta_app_id": "",
                    "app_base_url": "http://127.0.0.1:8000",
                }
            )

        self.assertEqual(merged["meta_app_id"], "env-app-id")
        self.assertEqual(merged["app_base_url"], "https://fredcore.vercel.app")


if __name__ == "__main__":
    unittest.main()
