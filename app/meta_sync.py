from __future__ import annotations

import os
from typing import Mapping

from app.report_sheets import REPORT_SHEET_DEFAULTS


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
    "google_ads_developer_token": "",
    "tiktok_app_id": "",
    "tiktok_app_secret": "",
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
    "include_zero_spend_rows": "INCLUDE_ZERO_SPEND_REPORTS",
    "job_trigger_token": "FREDCORE_JOB_TRIGGER_TOKEN",
    "google_reports_folder_id": "GOOGLE_REPORTS_FOLDER_ID",
    "google_monthly_report_sheet_tab_name": "GOOGLE_MONTHLY_REPORT_SHEET_TAB_NAME",
    "google_ads_developer_token": "GOOGLE_ADS_DEVELOPER_TOKEN",
    "tiktok_app_id": "TIKTOK_APP_ID",
    "tiktok_app_secret": "TIKTOK_APP_SECRET",
}


def merged_integration_settings(values: Mapping[str, str]) -> dict:
    merged = dict(INTEGRATION_DEFAULTS)
    for key, value in values.items():
        merged[key] = value
    for key, env_name in INTEGRATION_ENV_MAP.items():
        env_value = os.getenv(env_name)
        if env_value is not None and env_value.strip():
            merged[key] = env_value.strip()
    return merged
