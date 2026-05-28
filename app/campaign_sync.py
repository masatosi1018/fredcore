from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence

from app.config import ConfigError, normalize_account_id
from app.oauth_clients import OAuthAppConfig, refresh_google_access_token
from app.dates import iso_date, parse_target_date
from app.report_sheets import ensure_monthly_report_sheet
from app.transform import (
    MONTHLY_REPORT_HEADERS,
    build_campaign_report_row,
    campaign_row_key_from_values,
    compose_campaign_row_key,
)
from app.meta_sync import merged_integration_settings


@dataclass(frozen=True)
class MonthlyCampaignSyncConfig:
    meta_access_token: str
    meta_graph_api_version: str
    meta_request_timeout_seconds: int
    google_service_account_file: Path
    google_spreadsheet_id: str
    google_reports_folder_id: str
    google_monthly_report_sheet_tab_name: str
    google_oauth_client_id: str
    google_oauth_client_secret: str
    google_ads_developer_token: str
    tiktok_app_id: str
    tiktok_app_secret: str
    report_timezone: str

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, str],
        *,
        project_root: Path,
    ) -> "MonthlyCampaignSyncConfig":
        merged = merged_integration_settings(values)
        meta_access_token = merged.get("meta_access_token", "").strip()

        service_account_path = Path(
            merged.get("google_service_account_file", "").strip()
            or "config/google-service-account.json"
        )
        if not service_account_path.is_absolute():
            service_account_path = project_root / service_account_path

        google_spreadsheet_id = merged.get("google_spreadsheet_id", "").strip()
        google_reports_folder_id = str(merged.get("google_reports_folder_id", "")).strip()
        if not google_spreadsheet_id and not google_reports_folder_id:
            raise ConfigError(
                "Google 共有ドライブ配下のレポートフォルダID または Google スプレッドシートID を設定してください。"
            )

        return cls(
            meta_access_token=meta_access_token,
            meta_graph_api_version=merged.get("meta_graph_api_version", "").strip() or "v22.0",
            meta_request_timeout_seconds=int(
                merged.get("meta_request_timeout_seconds", "").strip() or "30"
            ),
            google_service_account_file=service_account_path,
            google_spreadsheet_id=google_spreadsheet_id,
            google_reports_folder_id=google_reports_folder_id,
            google_monthly_report_sheet_tab_name=(
                merged.get("google_monthly_report_sheet_tab_name", "").strip()
                or "キャンペーン一覧"
            ),
            google_oauth_client_id=merged.get("google_oauth_client_id", "").strip(),
            google_oauth_client_secret=merged.get("google_oauth_client_secret", "").strip(),
            google_ads_developer_token=merged.get("google_ads_developer_token", "").strip(),
            tiktok_app_id=merged.get("tiktok_app_id", "").strip(),
            tiktok_app_secret=merged.get("tiktok_app_secret", "").strip(),
            report_timezone=merged.get("report_timezone", "").strip() or "Asia/Tokyo",
        )


@dataclass(frozen=True)
class CampaignSheetTarget:
    spreadsheet_id: str
    spreadsheet_url: str
    spreadsheet_title: str
    created_spreadsheet: bool


def _resolve_account_access_token(account_row, repository, fallback_token: str) -> str:
    credential_profile_id = account_row["credential_profile_id"]
    if credential_profile_id:
        credential = repository.get_credential(int(credential_profile_id))
        if credential is not None:
            access_token = str(credential["access_token"] or "").strip()
            if access_token:
                return access_token
    return fallback_token.strip()


def _resolve_target_sheet(
    repository,
    *,
    month_key: str,
    settings: Mapping[str, str],
    project_root: Path,
    sheet_manager_factory: Optional[Callable[..., object]],
    config: MonthlyCampaignSyncConfig,
) -> CampaignSheetTarget:
    existing = repository.get_monthly_report_sheet(month_key)
    if existing:
        return CampaignSheetTarget(
            spreadsheet_id=str(existing["spreadsheet_id"]),
            spreadsheet_url=str(existing["spreadsheet_url"]),
            spreadsheet_title=str(existing["spreadsheet_title"]),
            created_spreadsheet=False,
        )

    merged = merged_integration_settings(settings)
    if config.google_reports_folder_id:
        created = ensure_monthly_report_sheet(
            repository,
            month_key=month_key,
            settings=merged,
            project_root=project_root,
            sheet_manager_factory=sheet_manager_factory,
        )
        return CampaignSheetTarget(
            spreadsheet_id=created.spreadsheet_id,
            spreadsheet_url=created.spreadsheet_url,
            spreadsheet_title=created.spreadsheet_title,
            created_spreadsheet=created.created,
        )

    return CampaignSheetTarget(
        spreadsheet_id=config.google_spreadsheet_id,
        spreadsheet_url=f"https://docs.google.com/spreadsheets/d/{config.google_spreadsheet_id}/edit",
        spreadsheet_title=f"{month_key} 固定スプレッドシート",
        created_spreadsheet=False,
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
    account_errors: List[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        object.__setattr__(self, "account_errors", self.account_errors or [])


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

    target_sheet = _resolve_target_sheet(
        repository,
        month_key=month_key,
        settings=settings,
        project_root=project_root,
        sheet_manager_factory=sheet_manager_factory,
        config=config,
    )

    active_accounts = [
        row
        for row in account_rows
        if str(row["platform"]).strip() == "meta" and int(row["sync_enabled"] or 1) == 1
    ]
    if not active_accounts:
        raise ConfigError("Meta アカウントが登録されていません。")

    if meta_client_factory is None:
        from app.meta_api import MetaClient

        meta_client_class = MetaClient
    else:
        meta_client_class = meta_client_factory

    keyed_rows = []
    client_by_token = {}
    account_count = 0
    account_errors: List[str] = []
    for account_row in active_accounts:
        raw_account_id = str(account_row["account_identifier"]).strip()
        if not raw_account_id:
            continue
        access_token = _resolve_account_access_token(account_row, repository, config.meta_access_token)
        if not access_token:
            account_name = str(account_row["account_name"] or raw_account_id).strip()
            raise ConfigError(
                f"{account_name} の Meta トークンがありません。認証プロフィールを再連携するか Meta アクセストークン を設定してください。"
            )
        account_id = normalize_account_id(raw_account_id)
        if access_token not in client_by_token:
            client_by_token[access_token] = meta_client_class(
                access_token=access_token,
                graph_api_version=config.meta_graph_api_version,
                timeout_seconds=config.meta_request_timeout_seconds,
            )
        try:
            records = client_by_token[access_token].fetch_account_daily_campaigns(
                account_id=account_id,
                report_date=report_date,
            )
        except Exception as exc:
            account_name = str(account_row["account_name"] or raw_account_id).strip()
            account_errors.append(f"{account_name}: {exc}")
            continue
        account_count += 1
        for record in records:
            if record.spend <= 0:
                continue
            keyed_rows.append(
                (
                    compose_campaign_row_key(
                        record.report_date,
                        record.platform,
                        record.account_name,
                        record.campaign_name,
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
        spreadsheet_id=target_sheet.spreadsheet_id,
        sheet_name=config.google_monthly_report_sheet_tab_name,
        headers=MONTHLY_REPORT_HEADERS,
        row_key_factory=campaign_row_key_from_values,
    )
    sheets_client.ensure_header()
    updated_count, appended_count = sheets_client.upsert_rows(keyed_rows)
    sheets_client.sort_rows()

    return MonthlyCampaignSyncResult(
        report_date=report_date,
        month_key=month_key,
        account_count=account_count,
        row_count=len(keyed_rows),
        updated_count=updated_count,
        appended_count=appended_count,
        spreadsheet_url=target_sheet.spreadsheet_url,
        spreadsheet_title=target_sheet.spreadsheet_title,
        created_spreadsheet=target_sheet.created_spreadsheet,
        account_errors=account_errors,
    )


def _get_google_access_token(credential_row, config: MonthlyCampaignSyncConfig) -> str:
    refresh_token = str(credential_row["refresh_token"] or "").strip()
    if not refresh_token:
        account_name = str(credential_row.get("profile_name") or credential_row.get("id") or "")
        raise ConfigError(
            f"{account_name} の Google リフレッシュトークンがありません。Google 認証をやり直してください。"
        )
    if not config.google_oauth_client_id or not config.google_oauth_client_secret:
        raise ConfigError(
            "Google OAuth クライアントID / シークレットを設定してください。"
        )
    oauth_config = OAuthAppConfig(
        platform="google",
        client_id=config.google_oauth_client_id,
        client_secret=config.google_oauth_client_secret,
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        redirect_uri="",
        scopes=(),
    )
    token = refresh_google_access_token(oauth_config, refresh_token)
    return token.access_token


def sync_google_ads_campaigns_to_monthly_sheet(
    account_rows: Sequence[Mapping[str, str]],
    *,
    settings: Mapping[str, str],
    project_root: Path,
    report_date_input: Optional[str] = None,
    google_ads_client_factory: Optional[Callable[..., object]] = None,
    sheets_client_factory: Optional[Callable[..., object]] = None,
    sheet_manager_factory: Optional[Callable[..., object]] = None,
    repository=None,
) -> MonthlyCampaignSyncResult:
    if repository is None:
        raise ConfigError("repository is required for monthly sheet sync.")

    config = MonthlyCampaignSyncConfig.from_mapping(settings, project_root=project_root)
    if not config.google_ads_developer_token:
        raise ConfigError(
            "Google Ads デベロッパートークンを設定してください。"
        )

    report_date = iso_date(parse_target_date(report_date_input, config.report_timezone))
    month_key = report_date[:7]

    target_sheet = _resolve_target_sheet(
        repository,
        month_key=month_key,
        settings=settings,
        project_root=project_root,
        sheet_manager_factory=sheet_manager_factory,
        config=config,
    )

    active_accounts = [
        row
        for row in account_rows
        if str(row["platform"]).strip() == "google" and int(row["sync_enabled"] or 1) == 1
    ]
    if not active_accounts:
        raise ConfigError("Google アカウントが登録されていません。")

    if google_ads_client_factory is None:
        from app.google_ads_api import GoogleAdsClient
        google_ads_client_class = GoogleAdsClient
    else:
        google_ads_client_class = google_ads_client_factory

    keyed_rows = []
    account_count = 0
    account_errors: List[str] = []
    for account_row in active_accounts:
        raw_customer_id = str(account_row["account_identifier"]).strip().replace("-", "")
        if not raw_customer_id:
            continue
        credential_profile_id = account_row["credential_profile_id"]
        if not credential_profile_id:
            account_name = str(account_row["account_name"] or raw_customer_id)
            raise ConfigError(
                f"{account_name} に認証プロフィールが紐づいていません。"
            )
        credential = repository.get_credential(int(credential_profile_id))
        if credential is None:
            raise ConfigError("認証プロフィールが見つかりません。")
        access_token = _get_google_access_token(credential, config)

        login_customer_id = str(account_row.get("parent_account") or "").replace("-", "").strip()
        client = google_ads_client_class(
            access_token=access_token,
            developer_token=config.google_ads_developer_token,
            login_customer_id=login_customer_id,
        )
        try:
            records = client.fetch_account_daily_campaigns(
                customer_id=raw_customer_id,
                report_date=report_date,
            )
        except Exception as exc:
            account_name = str(account_row["account_name"] or raw_customer_id)
            account_errors.append(f"{account_name}: {exc}")
            continue
        account_count += 1
        for record in records:
            if record.spend <= 0:
                continue
            keyed_rows.append(
                (
                    compose_campaign_row_key(
                        record.report_date,
                        record.platform,
                        record.account_name,
                        record.campaign_name,
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
        spreadsheet_id=target_sheet.spreadsheet_id,
        sheet_name=config.google_monthly_report_sheet_tab_name,
        headers=MONTHLY_REPORT_HEADERS,
        row_key_factory=campaign_row_key_from_values,
    )
    sheets_client.ensure_header()
    updated_count, appended_count = sheets_client.upsert_rows(keyed_rows)
    sheets_client.sort_rows()

    return MonthlyCampaignSyncResult(
        report_date=report_date,
        month_key=month_key,
        account_count=account_count,
        row_count=len(keyed_rows),
        updated_count=updated_count,
        appended_count=appended_count,
        spreadsheet_url=target_sheet.spreadsheet_url,
        spreadsheet_title=target_sheet.spreadsheet_title,
        created_spreadsheet=target_sheet.created_spreadsheet,
        account_errors=account_errors,
    )


def sync_tiktok_campaigns_to_monthly_sheet(
    account_rows: Sequence[Mapping[str, str]],
    *,
    settings: Mapping[str, str],
    project_root: Path,
    report_date_input: Optional[str] = None,
    tiktok_client_factory: Optional[Callable[..., object]] = None,
    sheets_client_factory: Optional[Callable[..., object]] = None,
    sheet_manager_factory: Optional[Callable[..., object]] = None,
    repository=None,
) -> MonthlyCampaignSyncResult:
    if repository is None:
        raise ConfigError("repository is required for monthly sheet sync.")

    config = MonthlyCampaignSyncConfig.from_mapping(settings, project_root=project_root)
    report_date = iso_date(parse_target_date(report_date_input, config.report_timezone))
    month_key = report_date[:7]

    target_sheet = _resolve_target_sheet(
        repository,
        month_key=month_key,
        settings=settings,
        project_root=project_root,
        sheet_manager_factory=sheet_manager_factory,
        config=config,
    )

    active_accounts = [
        row
        for row in account_rows
        if str(row["platform"]).strip() == "tiktok" and int(row["sync_enabled"] or 1) == 1
    ]
    if not active_accounts:
        raise ConfigError("TikTok アカウントが登録されていません。")

    if tiktok_client_factory is None:
        from app.tiktok_api import TikTokAdsClient
        tiktok_client_class = TikTokAdsClient
    else:
        tiktok_client_class = tiktok_client_factory

    keyed_rows = []
    client_by_token: dict = {}
    account_count = 0
    account_errors: List[str] = []
    for account_row in active_accounts:
        advertiser_id = str(account_row["account_identifier"]).strip()
        if not advertiser_id:
            continue
        access_token = _resolve_account_access_token(account_row, repository, "")
        if not access_token:
            account_name = str(account_row["account_name"] or advertiser_id)
            raise ConfigError(
                f"{account_name} の TikTok トークンがありません。認証プロフィールを再連携してください。"
            )
        if access_token not in client_by_token:
            client_by_token[access_token] = tiktok_client_class(access_token=access_token)
        try:
            records = client_by_token[access_token].fetch_account_daily_campaigns(
                advertiser_id=advertiser_id,
                report_date=report_date,
                advertiser_name=str(account_row.get("account_name") or advertiser_id),
            )
        except Exception as exc:
            account_name = str(account_row["account_name"] or advertiser_id)
            account_errors.append(f"{account_name}: {exc}")
            continue
        account_count += 1
        for record in records:
            if record.spend <= 0:
                continue
            keyed_rows.append(
                (
                    compose_campaign_row_key(
                        record.report_date,
                        record.platform,
                        record.account_name,
                        record.campaign_name,
                    ),
                    build_campaign_report_row(record),
                )
            )

    if sheets_client_factory is None:
        from app.sheets import GoogleSheetsTableClient
        tiktok_sheets_class = GoogleSheetsTableClient
    else:
        tiktok_sheets_class = sheets_client_factory
    sheets_client = tiktok_sheets_class(
        service_account_file=str(config.google_service_account_file),
        spreadsheet_id=target_sheet.spreadsheet_id,
        sheet_name=config.google_monthly_report_sheet_tab_name,
        headers=MONTHLY_REPORT_HEADERS,
        row_key_factory=campaign_row_key_from_values,
    )
    sheets_client.ensure_header()
    updated_count, appended_count = sheets_client.upsert_rows(keyed_rows)
    sheets_client.sort_rows()

    return MonthlyCampaignSyncResult(
        report_date=report_date,
        month_key=month_key,
        account_count=account_count,
        row_count=len(keyed_rows),
        updated_count=updated_count,
        appended_count=appended_count,
        spreadsheet_url=target_sheet.spreadsheet_url,
        spreadsheet_title=target_sheet.spreadsheet_title,
        created_spreadsheet=target_sheet.created_spreadsheet,
        account_errors=account_errors,
    )
