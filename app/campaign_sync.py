from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from app.config import ConfigError, normalize_account_id
from app.dates import iso_date, parse_target_date
from app.report_sheets import ensure_monthly_report_sheet
from app.transform import (
    MONTHLY_REPORT_HEADERS,
    build_campaign_report_row,
    campaign_row_key_from_values,
    compose_campaign_row_key,
)


@dataclass(frozen=True)
class MonthlyCampaignSyncConfig:
    meta_access_token: str
    meta_graph_api_version: str
    meta_request_timeout_seconds: int
    google_service_account_file: Path
    google_monthly_report_sheet_tab_name: str
    report_timezone: str

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, str],
        *,
        project_root: Path,
    ) -> "MonthlyCampaignSyncConfig":
        meta_access_token = values.get("meta_access_token", "").strip()
        if not meta_access_token:
            raise ConfigError("Meta アクセストークン を設定してください。")

        service_account_path = Path(
            values.get("google_service_account_file", "").strip()
            or "config/google-service-account.json"
        )
        if not service_account_path.is_absolute():
            service_account_path = project_root / service_account_path

        return cls(
            meta_access_token=meta_access_token,
            meta_graph_api_version=values.get("meta_graph_api_version", "").strip() or "v22.0",
            meta_request_timeout_seconds=int(
                values.get("meta_request_timeout_seconds", "").strip() or "30"
            ),
            google_service_account_file=service_account_path,
            google_monthly_report_sheet_tab_name=(
                values.get("google_monthly_report_sheet_tab_name", "").strip()
                or "キャンペーン一覧"
            ),
            report_timezone=values.get("report_timezone", "").strip() or "Asia/Tokyo",
        )


@dataclass(frozen=True)
class MonthlyCampaignSyncResult:
    report_date: str
    month_key: str
    account_count: int
    row_count: int
    updated_count: int
    appended_count: int
    spreadsheet_url: str
    spreadsheet_title: str
    created_spreadsheet: bool


def sync_meta_campaigns_to_monthly_sheet(
    account_rows: Sequence[Mapping[str, str]],
    *,
    settings: Mapping[str, str],
    project_root: Path,
    report_date_input: Optional[str] = None,
    meta_client_factory: Optional[Callable[..., object]] = None,
    sheets_client_factory: Optional[Callable[..., object]] = None,
    sheet_manager_factory: Optional[Callable[..., object]] = None,
    repository=None,
) -> MonthlyCampaignSyncResult:
    if repository is None:
        raise ConfigError("repository is required for monthly sheet sync.")

    config = MonthlyCampaignSyncConfig.from_mapping(settings, project_root=project_root)
    report_date = iso_date(parse_target_date(report_date_input, config.report_timezone))
    month_key = report_date[:7]

    monthly_sheet = ensure_monthly_report_sheet(
        repository,
        month_key=month_key,
        settings=settings,
        project_root=project_root,
        sheet_manager_factory=sheet_manager_factory,
    )

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
        records = meta_client.fetch_account_daily_campaigns(
            account_id=account_id,
            report_date=report_date,
        )
        for record in records:
            if record.spend <= 0:
                continue
            keyed_rows.append(
                (
                    compose_campaign_row_key(
                        record.report_date,
                        record.platform,
                        record.account_id,
                        record.campaign_id,
                    ),
                    build_campaign_report_row(record),
                )
            )

    if sheets_client_factory is None:
        from app.sheets import GoogleSheetsTableClient

        sheets_client_class = GoogleSheetsTableClient
    else:
        sheets_client_class = sheets_client_factory
    sheets_client = sheets_client_class(
        service_account_file=str(config.google_service_account_file),
        spreadsheet_id=monthly_sheet.spreadsheet_id,
        sheet_name=config.google_monthly_report_sheet_tab_name,
        headers=MONTHLY_REPORT_HEADERS,
        row_key_factory=campaign_row_key_from_values,
    )
    sheets_client.ensure_header()
    updated_count, appended_count = sheets_client.upsert_rows(keyed_rows)

    return MonthlyCampaignSyncResult(
        report_date=report_date,
        month_key=month_key,
        account_count=len(normalized_account_ids),
        row_count=len(keyed_rows),
        updated_count=updated_count,
        appended_count=appended_count,
        spreadsheet_url=monthly_sheet.spreadsheet_url,
        spreadsheet_title=monthly_sheet.spreadsheet_title,
        created_spreadsheet=monthly_sheet.created,
    )
