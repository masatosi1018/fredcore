from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class DailySpendRecord:
    report_date: str
    account_id: str
    account_name: str
    currency: str
    spend: Decimal
    timezone_name: str
    fetched_at: str
    source: str = "meta_marketing_api"


@dataclass(frozen=True)
class CampaignPerformanceRecord:
    report_date: str
    platform: str
    account_id: str
    account_name: str
    campaign_id: str
    campaign_name: str
    currency: str
    spend: Decimal
    impressions: int
    clicks: int
    conversions: Decimal
    timezone_name: str
    fetched_at: str
    source: str = "meta_marketing_api"
