from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False


class ConfigError(ValueError):
    """Raised when required environment variables are missing."""


def _load_env() -> None:
    load_dotenv()


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_account_id(account_id: str) -> str:
    normalized = account_id.strip()
    if normalized.startswith("act_"):
        return normalized[4:]
    return normalized


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Environment variable '{name}' is required.")
    return value


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    meta_access_token: str
    meta_ad_account_ids: List[str]
    meta_graph_api_version: str
    meta_request_timeout_seconds: int
    google_service_account_file: Path
    google_spreadsheet_id: str
    google_sheet_name: str
    report_timezone: str
    include_zero_spend_rows: bool

    @classmethod
    def from_env(cls) -> "Settings":
        _load_env()

        account_ids = [
            normalize_account_id(account_id)
            for account_id in _split_csv(_require("META_AD_ACCOUNT_IDS"))
        ]
        if not account_ids:
            raise ConfigError("At least one META_AD_ACCOUNT_IDS value is required.")

        return cls(
            meta_access_token=_require("META_ACCESS_TOKEN"),
            meta_ad_account_ids=account_ids,
            meta_graph_api_version=os.getenv("META_GRAPH_API_VERSION", "v22.0").strip(),
            meta_request_timeout_seconds=int(
                os.getenv("META_REQUEST_TIMEOUT_SECONDS", "30").strip()
            ),
            google_service_account_file=Path(
                os.getenv(
                    "GOOGLE_SERVICE_ACCOUNT_FILE",
                    "config/google-service-account.json",
                ).strip()
            ),
            google_spreadsheet_id=_require("GOOGLE_SPREADSHEET_ID"),
            google_sheet_name=os.getenv("GOOGLE_SHEET_NAME", "Meta Daily Spend").strip(),
            report_timezone=os.getenv("REPORT_TIMEZONE", "Asia/Tokyo").strip(),
            include_zero_spend_rows=_get_bool("INCLUDE_ZERO_SPEND_ROWS", True),
        )
