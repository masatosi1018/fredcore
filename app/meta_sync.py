from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
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
    for key, value in values.items():
        merged[key] = value
    for key, env_name in INTEGRATION_ENV_MAP.items():
        env_value = os.getenv(env_name)
        if env_value is not None and env_value.strip():
            merged[key] = env_value.strip()
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
        require_meta_access_token: bool = True,
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

        meta_access_token = merged.get("meta_access_token", "").strip()
        if require_meta_access_token and not meta_access_token:
            raise ConfigError("Meta アクセストークン を設定してください。")

        return cls(
            meta_access_token=meta_access_token,
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


@dataclass(frozen=True)
class MetaDailySyncResult:
    report_date: str
    account_count: int
    row_count: int
    updated_count: int
    appended_count: int
    success_count: int
    failure_count: int
    failure_messages: tuple[str, ...]


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


def _date_range(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _account_start_date(account_row, target_report_date: date) -> Optional[date]:
    last_synced_report_date = str(account_row["last_synced_report_date"] or "").strip()
    if last_synced_report_date:
        return date.fromisoformat(last_synced_report_date) + timedelta(days=1)

    created_at = str(account_row["created_at"] or "").strip()
    if created_at:
        try:
            created_date = datetime.fromisoformat(created_at).date()
        except ValueError:
            created_date = target_report_date
        return created_date
    return target_report_date


def _resolve_account_access_token(account_row, repository, fallback_token: str) -> str:
    credential_profile_id = account_row["credential_profile_id"]
    if credential_profile_id:
        credential = repository.get_credential(int(credential_profile_id))
        if credential is not None:
            access_token = str(credential["access_token"] or "").strip()
            if access_token:
                return access_token
    return fallback_token.strip()


def _preserve_sync_marker_for_forced_date(account_row, synced_report_date: str) -> str:
    existing_last_synced = str(account_row["last_synced_report_date"] or "").strip()
    if existing_last_synced:
        try:
            if date.fromisoformat(existing_last_synced) > date.fromisoformat(synced_report_date):
                return existing_last_synced
        except ValueError:
            pass

    created_at = str(account_row["created_at"] or "").strip()
    if created_at:
        try:
            if date.fromisoformat(synced_report_date) < datetime.fromisoformat(created_at).date():
                return ""
        except ValueError:
            pass
    return synced_report_date


def _sync_error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    if len(message) > 120:
        return f"{message[:117]}..."
    return message


def sync_linked_meta_accounts_to_sheet(
    account_rows: Sequence[Mapping[str, str]],
    *,
    settings: Mapping[str, str],
    repository,
    project_root: Path,
    report_date_input: Optional[str] = None,
    force_single_report_date: bool = False,
    meta_client_factory: Optional[Callable[..., object]] = None,
    sheets_client_factory: Optional[Callable[..., object]] = None,
) -> MetaDailySyncResult:
    config = MetaSheetSyncConfig.from_mapping(
        settings,
        project_root=project_root,
        require_meta_access_token=False,
    )
    target_report_date = parse_target_date(report_date_input, config.report_timezone)
    report_date = iso_date(target_report_date)
    fallback_token = config.meta_access_token.strip()

    active_accounts = [
        row
        for row in account_rows
        if str(row["platform"]).strip() == "meta" and int(row["sync_enabled"] or 1) == 1
    ]
    if not active_accounts:
        raise ConfigError("同期対象の Meta アカウントが登録されていません。")

    if meta_client_factory is None:
        from app.meta_api import MetaClient

        meta_client_class = MetaClient
    else:
        meta_client_class = meta_client_factory

    keyed_rows = []
    success_updates = []
    failure_updates = []
    failure_messages = []

    for account_row in active_accounts:
        account_db_id = int(account_row["id"])
        account_name = str(account_row["account_name"] or account_row["account_identifier"]).strip()
        raw_account_id = str(account_row["account_identifier"]).strip()
        if not raw_account_id:
            failure_updates.append((account_db_id, "失敗: アカウントIDが未設定です。"))
            failure_messages.append(f"{account_name}: アカウントIDが未設定です。")
            continue

        access_token = _resolve_account_access_token(account_row, repository, fallback_token)
        if not access_token:
            failure_updates.append((account_db_id, "失敗: Meta トークン未設定"))
            failure_messages.append(f"{account_name}: Meta トークン未設定")
            continue

        start_date = (
            target_report_date
            if force_single_report_date
            else _account_start_date(account_row, target_report_date)
        )
        if start_date is None or start_date > target_report_date:
            continue

        client = meta_client_class(
            access_token=access_token,
            graph_api_version=config.meta_graph_api_version,
            timeout_seconds=config.meta_request_timeout_seconds,
        )
        normalized_account_id = normalize_account_id(raw_account_id)
        last_report_date = ""
        try:
            for current_date in _date_range(start_date, target_report_date):
                current_report_date = iso_date(current_date)
                record = client.fetch_account_daily_spend(
                    account_id=normalized_account_id,
                    report_date=current_report_date,
                )
                if config.include_zero_spend_rows or record.spend != 0:
                    keyed_rows.append(
                        (
                            compose_row_key(record.report_date, record.account_id),
                            build_sheet_row(record),
                        )
                    )
                last_report_date = current_report_date
        except Exception as exc:
            message = _sync_error_message(exc)
            failure_updates.append((account_db_id, f"失敗: {message}"))
            failure_messages.append(f"{account_name}: {message}")
            continue

        if last_report_date:
            success_updates.append(
                (
                    account_db_id,
                    (
                        _preserve_sync_marker_for_forced_date(account_row, last_report_date)
                        if force_single_report_date
                        else last_report_date
                    ),
                )
            )

    updated_count = 0
    appended_count = 0
    if keyed_rows:
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

    synced_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for account_db_id, last_report_date in success_updates:
        repository.update_account_sync_state(
            account_db_id,
            sync_status="同期済み",
            last_synced_at=synced_at,
            last_synced_report_date=last_report_date,
        )
    for account_db_id, status in failure_updates:
        repository.update_account_sync_state(
            account_db_id,
            sync_status=status,
        )

    return MetaDailySyncResult(
        report_date=report_date,
        account_count=len(active_accounts),
        row_count=len(keyed_rows),
        updated_count=updated_count,
        appended_count=appended_count,
        success_count=len(success_updates),
        failure_count=len(failure_updates),
        failure_messages=tuple(failure_messages),
    )
