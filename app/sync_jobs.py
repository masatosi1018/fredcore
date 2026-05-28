from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from app.campaign_sync import (
    MonthlyCampaignSyncResult,
    sync_google_ads_campaigns_to_monthly_sheet,
    sync_meta_campaigns_to_monthly_sheet,
    sync_tiktok_campaigns_to_monthly_sheet,
)
from app.dates import iso_date, parse_target_date


@dataclass(frozen=True)
class SyncJobResult:
    sync_run_id: int
    result: MonthlyCampaignSyncResult


def run_meta_monthly_sync_job(
    repository,
    *,
    settings: Mapping[str, str],
    project_root: Path,
    report_date_input: Optional[str] = None,
    trigger_source: str = "manual",
    meta_client_factory: Optional[Callable[..., object]] = None,
    sheets_client_factory: Optional[Callable[..., object]] = None,
    sheet_manager_factory: Optional[Callable[..., object]] = None,
) -> SyncJobResult:
    timezone_name = settings.get("report_timezone", "").strip() or "Asia/Tokyo"
    report_date = iso_date(parse_target_date(report_date_input, timezone_name))
    month_key = report_date[:7]
    sync_run_id = repository.create_sync_run(
        job_name="meta_monthly_campaign_sync",
        platform="meta",
        trigger_source=trigger_source,
        report_date=report_date,
        month_key=month_key,
    )
    try:
        result = sync_meta_campaigns_to_monthly_sheet(
            repository.list_accounts("meta"),
            settings=settings,
            project_root=project_root,
            report_date_input=report_date,
            meta_client_factory=meta_client_factory,
            sheets_client_factory=sheets_client_factory,
            sheet_manager_factory=sheet_manager_factory,
            repository=repository,
        )
    except Exception as exc:
        repository.complete_sync_run(
            sync_run_id,
            status="失敗",
            error_message=str(exc),
        )
        raise

    repository.complete_sync_run(
        sync_run_id,
        status="成功",
        account_count=result.account_count,
        row_count=result.row_count,
        updated_count=result.updated_count,
        appended_count=result.appended_count,
        spreadsheet_url=result.spreadsheet_url,
        spreadsheet_title=result.spreadsheet_title,
        error_message="\n".join(result.account_errors) if result.account_errors else "",
    )
    return SyncJobResult(sync_run_id=sync_run_id, result=result)


def run_google_ads_monthly_sync_job(
    repository,
    *,
    settings: Mapping[str, str],
    project_root: Path,
    report_date_input: Optional[str] = None,
    trigger_source: str = "manual",
    google_ads_client_factory: Optional[Callable[..., object]] = None,
    sheets_client_factory: Optional[Callable[..., object]] = None,
    sheet_manager_factory: Optional[Callable[..., object]] = None,
) -> SyncJobResult:
    timezone_name = settings.get("report_timezone", "").strip() or "Asia/Tokyo"
    report_date = iso_date(parse_target_date(report_date_input, timezone_name))
    month_key = report_date[:7]
    sync_run_id = repository.create_sync_run(
        job_name="google_ads_monthly_campaign_sync",
        platform="google",
        trigger_source=trigger_source,
        report_date=report_date,
        month_key=month_key,
    )
    try:
        result = sync_google_ads_campaigns_to_monthly_sheet(
            repository.list_accounts("google"),
            settings=settings,
            project_root=project_root,
            report_date_input=report_date,
            google_ads_client_factory=google_ads_client_factory,
            sheets_client_factory=sheets_client_factory,
            sheet_manager_factory=sheet_manager_factory,
            repository=repository,
        )
    except Exception as exc:
        repository.complete_sync_run(
            sync_run_id,
            status="失敗",
            error_message=str(exc),
        )
        raise

    repository.complete_sync_run(
        sync_run_id,
        status="成功",
        account_count=result.account_count,
        row_count=result.row_count,
        updated_count=result.updated_count,
        appended_count=result.appended_count,
        spreadsheet_url=result.spreadsheet_url,
        spreadsheet_title=result.spreadsheet_title,
        error_message="\n".join(result.account_errors) if result.account_errors else "",
    )
    return SyncJobResult(sync_run_id=sync_run_id, result=result)


def run_tiktok_monthly_sync_job(
    repository,
    *,
    settings: Mapping[str, str],
    project_root: Path,
    report_date_input: Optional[str] = None,
    trigger_source: str = "manual",
    tiktok_client_factory: Optional[Callable[..., object]] = None,
    sheets_client_factory: Optional[Callable[..., object]] = None,
    sheet_manager_factory: Optional[Callable[..., object]] = None,
) -> SyncJobResult:
    timezone_name = settings.get("report_timezone", "").strip() or "Asia/Tokyo"
    report_date = iso_date(parse_target_date(report_date_input, timezone_name))
    month_key = report_date[:7]
    sync_run_id = repository.create_sync_run(
        job_name="tiktok_monthly_campaign_sync",
        platform="tiktok",
        trigger_source=trigger_source,
        report_date=report_date,
        month_key=month_key,
    )
    try:
        result = sync_tiktok_campaigns_to_monthly_sheet(
            repository.list_accounts("tiktok"),
            settings=settings,
            project_root=project_root,
            report_date_input=report_date,
            tiktok_client_factory=tiktok_client_factory,
            sheets_client_factory=sheets_client_factory,
            sheet_manager_factory=sheet_manager_factory,
            repository=repository,
        )
    except Exception as exc:
        repository.complete_sync_run(
            sync_run_id,
            status="失敗",
            error_message=str(exc),
        )
        raise

    repository.complete_sync_run(
        sync_run_id,
        status="成功",
        account_count=result.account_count,
        row_count=result.row_count,
        updated_count=result.updated_count,
        appended_count=result.appended_count,
        spreadsheet_url=result.spreadsheet_url,
        spreadsheet_title=result.spreadsheet_title,
        error_message="\n".join(result.account_errors) if result.account_errors else "",
    )
    return SyncJobResult(sync_run_id=sync_run_id, result=result)
