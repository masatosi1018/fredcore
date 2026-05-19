from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

import requests

from app.models import CampaignPerformanceRecord


GOOGLE_ADS_API_VERSION = "v18"
GOOGLE_ADS_BASE_URL = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"

_CAMPAIGN_QUERY = (
    "SELECT"
    " campaign.id,"
    " campaign.name,"
    " customer.descriptive_name,"
    " customer.id,"
    " segments.date,"
    " metrics.cost_micros,"
    " metrics.impressions,"
    " metrics.clicks,"
    " metrics.conversions"
    " FROM campaign"
    " WHERE segments.date = '{date}'"
)


class GoogleAdsError(RuntimeError):
    """Raised when the Google Ads API returns an error response."""


class GoogleAdsClient:
    def __init__(
        self,
        access_token: str,
        developer_token: str,
        login_customer_id: str = "",
        timeout_seconds: int = 30,
    ):
        self.access_token = access_token
        self.developer_token = developer_token
        self.login_customer_id = login_customer_id.replace("-", "").strip()
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "developer-token": self.developer_token,
            "Content-Type": "application/json",
        }
        if self.login_customer_id:
            headers["login-customer-id"] = self.login_customer_id
        return headers

    def _search(self, customer_id: str, query: str, page_token: str = "") -> Dict[str, Any]:
        body: Dict[str, Any] = {"query": query}
        if page_token:
            body["pageToken"] = page_token
        response = self.session.post(
            f"{GOOGLE_ADS_BASE_URL}/customers/{customer_id}/googleAds:search",
            headers=self._headers(),
            json=body,
            timeout=self.timeout_seconds,
        )
        if not response.ok:
            try:
                error_body = response.json()
            except ValueError:
                raise GoogleAdsError(
                    f"Google Ads API error ({response.status_code}): {response.text[:400]}"
                )
            error_detail = error_body.get("error", {})
            if isinstance(error_detail, dict):
                message = error_detail.get("message") or str(error_body)
            else:
                message = str(error_detail or error_body)
            raise GoogleAdsError(f"Google Ads API error: {message}")
        return response.json()

    def fetch_account_daily_campaigns(
        self,
        customer_id: str,
        report_date: str,
    ) -> List[CampaignPerformanceRecord]:
        clean_id = customer_id.replace("-", "").strip()
        query = _CAMPAIGN_QUERY.format(date=report_date)
        fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        records: List[CampaignPerformanceRecord] = []
        next_page = ""
        while True:
            payload = self._search(clean_id, query, next_page)
            for row in payload.get("results", []):
                campaign = row.get("campaign", {})
                customer = row.get("customer", {})
                metrics = row.get("metrics", {})
                segments = row.get("segments", {})
                cost_micros = int(metrics.get("costMicros", 0) or 0)
                spend = Decimal(str(cost_micros)) / Decimal("1000000")
                records.append(
                    CampaignPerformanceRecord(
                        report_date=str(segments.get("date") or report_date),
                        platform="google",
                        account_id=str(customer.get("id") or clean_id),
                        account_name=str(customer.get("descriptiveName") or clean_id),
                        campaign_id=str(campaign.get("id") or ""),
                        campaign_name=str(campaign.get("name") or ""),
                        currency="",
                        spend=spend,
                        impressions=int(metrics.get("impressions", 0) or 0),
                        clicks=int(metrics.get("clicks", 0) or 0),
                        conversions=Decimal(str(metrics.get("conversions", 0) or 0)),
                        timezone_name="",
                        fetched_at=fetched_at,
                        source="google_ads_api",
                    )
                )
            next_page = payload.get("nextPageToken", "")
            if not next_page:
                break
        return records
