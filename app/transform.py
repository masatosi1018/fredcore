from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Sequence

from app.models import CampaignPerformanceRecord


MONTHLY_REPORT_HEADERS = [
    "日付",
    "媒体",
    "広告アカウント名",
    "キャンペーン名",
    "消化金額",
    "表示回数",
    "クリック数",
    "コンバージョン数",
    "取得日時",
]


def compose_campaign_row_key(
    report_date: str,
    platform: str,
    account_id: str,
    campaign_id: str,
) -> str:
    return f"{report_date}::{platform}::{account_id}::{campaign_id}"


def decimal_to_sheet_value(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_campaign_report_row(record: CampaignPerformanceRecord) -> List[str]:
    return [
        record.report_date,
        record.platform,
        record.account_name,
        record.campaign_name,
        decimal_to_sheet_value(record.spend),
        str(record.impressions),
        str(record.clicks),
        decimal_to_sheet_value(record.conversions),
        record.fetched_at[:10],
    ]


def campaign_row_key_from_values(row: Sequence[str]) -> str:
    if len(row) < 4:
        return ""
    return compose_campaign_row_key(row[0], row[1], row[2], row[3])
