from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from app.config import ConfigError, normalize_account_id
from app.dates import iso_date, parse_target_date
from app.report_sheets import REPORT_SHEET_DEFAULTS
from app.transform import build_sheet_row, compose_row_key


INTEGRATION_DEFAULTS = {
    "app_base_url": "http://127.0.0.1:8000",
    "meta_access_token": "",
    "meta_app_id": "",
    "meta_app_secret": "",
    "meta_graph_api_version": "v22.0",
    "meta_request_timeout_seconds": "30",
    "google_service_account_file": "config/google-service-account.json",
    "google_oauth_client_id": "",
    "google_oauth_client_secret": "",
    "google_spreadsheet_id": "",
    "google_sheet_name": "Meta Daily Spend",
    "report_timezone": "Asia/Tokyo",
    "include_zero_spend_rows": "true",
    "job_trigger_token": "",
}
INTEGRATION_DEFAULTS.update(REPORT_SHEET_DEFAULTS)

INTEGRATION_ENV_MAP = {
    "app_base_url": "FREDCORE_APP_BASE_URL",
    "meta_access_token": "META_ACCESS_TOKEN",
    "meta_app_id": "META_APP_ID",
    "meta_app_secret": "META_APP_SECRET",
    "meta_graph_api_version": "META_GRAPH_API_VERSION",
    "meta_request_timeout_seconds": "META_REQUEST_TIMEOUT_SECONDS",
    "google_service_account_file": "GOOGLE_SERVICE_ACCOUNT_FILE",
    "google_oauth_client_id": "GOOGLE_OAUTH_CLIENT_ID",
    "google_oauth_client_secret": "GOOGLE_OAUTH_CLIENT_SECRET",
    "google_spreadsheet_id": "GOOGLE_SPREADSHEET_ID",
    "google_sheet_name": "GOOGLE_SHEET_NAME",
    "report_timezone": "REPORT_TIMEZONE",
    "include_zero_spend_rows": "INCLUDE_ZERO_SPEND_ROWS",
    "job_trigger_token": "FREDCORE_JOB_TRIGGER_TOKEN",
    "google_reports_folder_id": "GOOGLE_REPORTS_FOLDER_ID",
    "google_monthly_report_sheet_tab_name": "GOOGLE_MONTHLY_REPORT_SHEET_TAB_NAME",
}


def _bool_value(raw_value: str) -> bool:
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def merged_integration_settings(values: Mapping[str, str]) -> dict:
    merged = dict(INTEGRATION_DEFAULTS)
    for key, env_name in INTEGRATION_ENV_MAP.items():
        env_value = os.getenv(env_name)
        if env_value is not None and env_value.strip():
            merged[key] = env_value.strip()
    for key, value in values.items():
        merged[key] = value
    return merged


@dataclass(frozen=True)
class MetaSheetSyncConfig:
    meta_access_token: str
    meta_graph_api_version: str
    meta_request_timeout_seconds: int
    google_service_account_file: Path
    google_spreadsheet_id: str
    google_sheet_name: str
    report_timezone: str
    include_zero_spend_rows: bool

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, str],
        *,
        project_root: Path,
    ) -> "MetaSheetSyncConfig":
        merged = merged_integration_settings(values)

        def require(name: str, label: str) -> str:
            value = merged.get(name, "").strip()
            if not value:
                raise ConfigError(f"{label} を設定してください。")
            return value

        service_account_path = Path(
            require("google_service_account_file", "Google サービスアカウント JSON パス")
        )
        if not service_account_path.is_absolute():
            service_account_path = project_root / service_account_path

        return cls(
            meta_access_token=require("meta_access_token", "Meta アクセストークン"),
            meta_graph_api_version=merged["meta_graph_api_version"].strip() or "v22.0",
            meta_request_timeout_seconds=int(
                merged["meta_request_timeout_seconds"].strip() or "30"
            ),
            google_service_account_file=service_account_path,
            google_spreadsheet_id=require("google_spreadsheet_id", "Google スプレッドシートID"),
            google_sheet_name=merged["google_sheet_name"].strip() or "Meta Daily Spend",
            report_timezone=merged["report_timezone"].strip() or "Asia/Tokyo",
            include_zero_spend_rows=_bool_value(
                merged.get("include_zero_spend_rows", "true")
            ),
        )


@dataclass(frozen=True)
class MetaSyncResult:
    report_date: str
    account_count: int
    row_count: int
    updated_count: int
    appended_count: int


def sync_meta_accounts_to_sheet(
    account_rows: Sequence[Mapping[str, str]],
    *,
    config: MetaSheetSyncConfig,
    report_date_input: Optional[str] = None,
    meta_client_factory: Optional[Callable[..., object]] = None,
    sheets_client_factory: Optional[Callable[..., object]] = None,
) -> MetaSyncResult:
    normalized_account_ids = []
    for row in account_rows:
        raw_account_id = str(row["account_identifier"]).strip()
        if not raw_account_id:
            continue
        normalized = normalize_account_id(raw_account_id)
        if normalized not in normalized_account_ids:
            normalized_account_ids.append(normalized)

    if not normalized_account_ids:
        raise ConfigError("Meta アカウントが登録されていません。")

    report_date = iso_date(parse_target_date(report_date_input, config.report_timezone))
    if meta_client_factory is None:
        from app.meta_api import MetaClient

        meta_client_class = MetaClient
    else:
        meta_client_class = meta_client_factory
    meta_client = meta_client_class(
        access_token=config.meta_access_token,
        graph_api_version=config.meta_graph_api_version,
        timeout_seconds=config.meta_request_timeout_seconds,
    )

    keyed_rows = []
    for account_id in normalized_account_ids:
        record = meta_client.fetch_account_daily_spend(
            account_id=account_id,
            report_date=report_date,
        )
        if not config.include_zero_spend_rows and record.spend == 0:
            continue

        keyed_rows.append(
            (
                compose_row_key(record.report_date, record.account_id),
                build_sheet_row(record),
            )
        )

    if sheets_client_factory is None:
        from app.sheets import GoogleSheetsClient

        sheets_client_class = GoogleSheetsClient
    else:
        sheets_client_class = sheets_client_factory
    sheets_client = sheets_client_class(
        service_account_file=str(config.google_service_account_file),
        spreadsheet_id=config.google_spreadsheet_id,
        sheet_name=config.google_sheet_name,
    )
    sheets_client.ensure_header()
    updated_count, appended_count = sheets_client.upsert_rows(keyed_rows)

    return MetaSyncResult(
        report_date=report_date,
        account_count=len(normalized_account_ids),
        row_count=len(keyed_rows),
        updated_count=updated_count,
        appended_count=appended_count,
    )
