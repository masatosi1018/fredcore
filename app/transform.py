from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Sequence

from app.models import CampaignPerformanceRecord, DailySpendRecord


SHEET_HEADERS = [
    "date",
    "account_id",
    "account_name",
    "currency",
    "spend",
    "timezone_name",
    "fetched_at",
    "source",
]

MONTHLY_REPORT_HEADERS = [
    "日付",
    "媒体",
    "広告アカウントID",
    "広告アカウント名",
    "キャンペーンID",
    "キャンペーン名",
    "通貨",
    "消化金額",
    "表示回数",
    "クリック数",
    "コンバージョン数",
    "タイムゾーン",
    "取得日時",
    "データソース",
]


def compose_row_key(report_date: str, account_id: str) -> str:
    return f"{report_date}::{account_id}"


def compose_campaign_row_key(
    report_date: str,
    platform: str,
    account_id: str,
    campaign_id: str,
) -> str:
    return f"{report_date}::{platform}::{account_id}::{campaign_id}"


def decimal_to_sheet_value(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_sheet_row(record: DailySpendRecord) -> List[str]:
    return [
        record.report_date,
        record.account_id,
        record.account_name,
        record.currency,
        decimal_to_sheet_value(record.spend),
        record.timezone_name,
        record.fetched_at,
        record.source,
    ]


def build_campaign_report_row(record: CampaignPerformanceRecord) -> List[str]:
    return [
        record.report_date,
        record.platform,
        record.account_id,
        record.account_name,
        record.campaign_id,
        record.campaign_name,
        record.currency,
        decimal_to_sheet_value(record.spend),
        str(record.impressions),
        str(record.clicks),
        decimal_to_sheet_value(record.conversions),
        record.timezone_name,
        record.fetched_at,
        record.source,
    ]


def row_key_from_values(row: Sequence[str]) -> str:
    if len(row) < 2:
        return ""
    return compose_row_key(row[0], row[1])


def campaign_row_key_from_values(row: Sequence[str]) -> str:
    if len(row) < 5:
        return ""
    return compose_campaign_row_key(row[0], row[1], row[2], row[4])
