from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from app.config import ConfigError


REPORT_SHEET_DEFAULTS = {
    "google_reports_folder_id": "",
    "google_monthly_report_sheet_tab_name": "キャンペーン一覧",
}


def merged_report_sheet_settings(values: Mapping[str, str]) -> dict:
    merged = dict(REPORT_SHEET_DEFAULTS)
    for key, value in values.items():
        merged[key] = value
    return merged


def extract_drive_folder_id(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""

    patterns = [
        r"/folders/([a-zA-Z0-9_-]+)",
        r"[?&]folder=([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return value


def normalize_month_key(raw_value: str) -> str:
    return raw_value.strip()


def build_monthly_report_title(month_key: str) -> str:
    year, month = normalize_month_key(month_key).split("-")
    return f"{int(year)}年{int(month)}月 広告消化キャンペーン一覧"


@dataclass(frozen=True)
class MonthlyReportSheetConfig:
    google_service_account_file: Path
    google_reports_folder_id: str
    google_monthly_report_sheet_tab_name: str

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, str],
        *,
        project_root: Path,
    ) -> "MonthlyReportSheetConfig":
        merged = merged_report_sheet_settings(values)
        service_account_path = Path(
            merged.get("google_service_account_file", "").strip()
            or "config/google-service-account.json"
        )
        if not service_account_path.is_absolute():
            service_account_path = project_root / service_account_path

        folder_id = extract_drive_folder_id(merged.get("google_reports_folder_id", ""))
        if not folder_id:
            raise ConfigError("Google 共有ドライブ配下のレポートフォルダID を設定してください。")

        return cls(
            google_service_account_file=service_account_path,
            google_reports_folder_id=folder_id,
            google_monthly_report_sheet_tab_name=(
                merged.get("google_monthly_report_sheet_tab_name", "").strip()
                or REPORT_SHEET_DEFAULTS["google_monthly_report_sheet_tab_name"]
            ),
        )


@dataclass(frozen=True)
class MonthlyReportSheetResult:
    month_key: str
    spreadsheet_id: str
    spreadsheet_url: str
    spreadsheet_title: str
    created: bool


def ensure_monthly_report_sheet(
    repository,
    *,
    month_key: str,
    settings: Mapping[str, str],
    project_root: Path,
    sheet_manager_factory: Optional[Callable[..., object]] = None,
) -> MonthlyReportSheetResult:
    normalized_month_key = normalize_month_key(month_key)
    existing = repository.get_monthly_report_sheet(normalized_month_key)
    if existing:
        return MonthlyReportSheetResult(
            month_key=normalized_month_key,
            spreadsheet_id=str(existing["spreadsheet_id"]),
            spreadsheet_url=str(existing["spreadsheet_url"]),
            spreadsheet_title=str(existing["spreadsheet_title"]),
            created=False,
        )

    config = MonthlyReportSheetConfig.from_mapping(settings, project_root=project_root)
    if sheet_manager_factory is None:
        from app.sheets import GoogleDriveSheetsManager

        manager_class = GoogleDriveSheetsManager
    else:
        manager_class = sheet_manager_factory

    manager = manager_class(
        service_account_file=str(config.google_service_account_file),
    )
    spreadsheet_title = build_monthly_report_title(normalized_month_key)
    created = manager.create_spreadsheet_in_folder(
        title=spreadsheet_title,
        folder_id=config.google_reports_folder_id,
        initial_sheet_name=config.google_monthly_report_sheet_tab_name,
    )
    repository.save_monthly_report_sheet(
        month_key=normalized_month_key,
        spreadsheet_url=created["spreadsheet_url"],
        spreadsheet_title=created["spreadsheet_title"],
        status="有効",
        notes="共有ドライブへ自動作成",
    )
    saved = repository.get_monthly_report_sheet(normalized_month_key)
    return MonthlyReportSheetResult(
        month_key=normalized_month_key,
        spreadsheet_id=str(saved["spreadsheet_id"]),
        spreadsheet_url=str(saved["spreadsheet_url"]),
        spreadsheet_title=str(saved["spreadsheet_title"]),
        created=True,
    )
