import tempfile
import unittest
from pathlib import Path

from app.admin_db import AdminRepository
from app.report_sheets import (
    MonthlyReportSheetConfig,
    build_monthly_report_title,
    ensure_monthly_report_sheet,
    extract_drive_folder_id,
)


class FakeSheetManager:
    def __init__(self, service_account_file):
        self.service_account_file = service_account_file

    def create_spreadsheet_in_folder(self, *, title, folder_id, initial_sheet_name):
        return {
            "spreadsheet_id": "sheet-created-123",
            "spreadsheet_title": title,
            "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/sheet-created-123/edit#gid=0&folder={folder_id}&tab={initial_sheet_name}",
        }


class ReportSheetsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "fredcore.db"
        self.repository = AdminRepository(self.database_path)
        self.repository.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_extract_drive_folder_id_from_url(self):
        folder_id = extract_drive_folder_id(
            "https://drive.google.com/drive/folders/folder-123abc?usp=sharing"
        )
        self.assertEqual(folder_id, "folder-123abc")

    def test_build_monthly_report_title(self):
        self.assertEqual(
            build_monthly_report_title("2026-04"),
            "2026年4月 広告消化キャンペーン一覧",
        )

    def test_monthly_report_config_accepts_folder_url(self):
        config = MonthlyReportSheetConfig.from_mapping(
            {
                "google_service_account_file": "service.json",
                "google_reports_folder_id": "https://drive.google.com/drive/folders/folder-xyz",
            },
            project_root=Path(self.temp_dir.name),
        )
        self.assertEqual(config.google_reports_folder_id, "folder-xyz")
        self.assertEqual(
            config.google_monthly_report_sheet_tab_name,
            "キャンペーン一覧",
        )

    def test_ensure_monthly_report_sheet_creates_and_saves(self):
        result = ensure_monthly_report_sheet(
            self.repository,
            month_key="2025-03",
            settings={
                "google_service_account_file": "service.json",
                "google_reports_folder_id": "folder-abc",
                "google_monthly_report_sheet_tab_name": "一覧",
            },
            project_root=Path(self.temp_dir.name),
            sheet_manager_factory=FakeSheetManager,
        )
        self.assertTrue(result.created)
        self.assertEqual(result.spreadsheet_id, "sheet-created-123")
        saved = self.repository.get_monthly_report_sheet("2025-03")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["spreadsheet_id"], "sheet-created-123")

    def test_ensure_monthly_report_sheet_reuses_existing(self):
        self.repository.save_monthly_report_sheet(
            month_key="2026-05",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/existing-sheet/edit#gid=0",
            spreadsheet_title="2026年5月 広告消化キャンペーン一覧",
        )
        result = ensure_monthly_report_sheet(
            self.repository,
            month_key="2026-05",
            settings={
                "google_service_account_file": "service.json",
                "google_reports_folder_id": "folder-abc",
            },
            project_root=Path(self.temp_dir.name),
            sheet_manager_factory=FakeSheetManager,
        )
        self.assertFalse(result.created)
        self.assertEqual(result.spreadsheet_id, "existing-sheet")


if __name__ == "__main__":
    unittest.main()
