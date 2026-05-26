from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

import requests

from app.models import CampaignPerformanceRecord


TIKTOK_API_BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"


class TikTokAdsError(RuntimeError):
    """Raised when the TikTok Ads API returns an error response."""


class TikTokAdsClient:
    def __init__(self, access_token: str, app_id: str = "", secret: str = "", timeout_seconds: int = 30):
        self.access_token = access_token
        self.app_id = app_id
        self.secret = secret
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {"Access-Token": self.access_token}

    def list_accessible_advertisers(self) -> List[Dict[str, str]]:
        """Return all advertiser accounts accessible to the authenticated user."""
        response = self.session.get(
            f"{TIKTOK_API_BASE_URL}/oauth2/advertiser/get/",
            headers=self._headers(),
            params={
                "app_id": self.app_id,
                "secret": self.secret,
                "access_token": self.access_token,
            },
            timeout=self.timeout_seconds,
        )
        try:
            body = response.json()
        except ValueError:
            raise TikTokAdsError(f"TikTok API error ({response.status_code}): {response.text[:400]}")
        code = body.get("code", -1)
        if code != 0:
            message = body.get("message") or str(body)
            raise TikTokAdsError(f"TikTok API error [{code}]: {message}")
        items = body.get("data", {}).get("list", [])
        return [
            {
                "account_id": str(item.get("advertiser_id") or ""),
                "account_name": str(item.get("advertiser_name") or item.get("advertiser_id") or ""),
                "status": "ENABLED",
            }
            for item in items
            if item.get("advertiser_id")
        ]

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        response = self.session.get(
            f"{TIKTOK_API_BASE_URL}{path}",
            headers=self._headers(),
            params=params,
            timeout=self.timeout_seconds,
        )
        try:
            body = response.json()
        except ValueError:
            raise TikTokAdsError(f"TikTok API error ({response.status_code}): {response.text[:400]}")
        code = body.get("code", -1)
        if code != 0:
            message = body.get("message") or str(body)
            raise TikTokAdsError(f"TikTok API error [{code}]: {message}")
        return body.get("data", {})

    def _fetch_campaign_names(self, advertiser_id: str) -> Dict[str, str]:
        name_map: Dict[str, str] = {}
        page = 1
        while True:
            data = self._get(
                "/campaign/get/",
                {
                    "advertiser_id": advertiser_id,
                    "fields": json.dumps(["campaign_id", "campaign_name"]),
                    "page": page,
                    "page_size": 1000,
                },
            )
            for row in data.get("list", []):
                cid = str(row.get("campaign_id") or "")
                cname = str(row.get("campaign_name") or cid)
                if cid:
                    name_map[cid] = cname
            page_info = data.get("page_info", {})
            if page >= int(page_info.get("total_page", 1) or 1):
                break
            page += 1
        return name_map

    def fetch_account_daily_campaigns(
        self,
        advertiser_id: str,
        report_date: str,
        advertiser_name: str = "",
    ) -> List[CampaignPerformanceRecord]:
        try:
            campaign_names = self._fetch_campaign_names(advertiser_id)
        except TikTokAdsError:
            campaign_names = {}
        display_name = advertiser_name or advertiser_id
        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        records: List[CampaignPerformanceRecord] = []
        page = 1
        while True:
            data = self._get(
                "/report/integrated/get/",
                {
                    "advertiser_id": advertiser_id,
                    "report_type": "BASIC",
                    "data_level": "AUCTION_CAMPAIGN",
                    "dimensions": json.dumps(["campaign_id", "stat_time_day"]),
                    "metrics": json.dumps(["spend", "impressions", "clicks", "conversion"]),
                    "start_date": report_date,
                    "end_date": report_date,
                    "page": page,
                    "page_size": 1000,
                },
            )
            for row in data.get("list", []):
                dims = row.get("dimensions", {})
                metrics = row.get("metrics", {})
                campaign_id = str(dims.get("campaign_id") or "")
                campaign_name = campaign_names.get(campaign_id, campaign_id)
                spend = Decimal(str(metrics.get("spend", "0") or "0"))
                records.append(
                    CampaignPerformanceRecord(
                        report_date=report_date,
                        platform="tiktok",
                        account_id=advertiser_id,
                        account_name=display_name,
                        campaign_id=campaign_id,
                        campaign_name=campaign_name,
                        currency="",
                        spend=spend,
                        impressions=int(metrics.get("impressions", 0) or 0),
                        clicks=int(metrics.get("clicks", 0) or 0),
                        conversions=Decimal(str(metrics.get("conversion", "0") or "0")),
                        timezone_name="",
                        fetched_at=fetched_at,
                        source="tiktok_ads_api",
                    )
                )
            page_info = data.get("page_info", {})
            if page >= int(page_info.get("total_page", 1) or 1):
                break
            page += 1
        return records
