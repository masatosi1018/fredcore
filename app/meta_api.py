from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

import requests

from app.models import CampaignPerformanceRecord


class MetaApiError(RuntimeError):
    """Raised when the Meta API returns an error response."""


class MetaClient:
    def __init__(self, access_token: str, graph_api_version: str, timeout_seconds: int = 30):
        self.access_token = access_token
        self.graph_api_version = graph_api_version
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def fetch_account_daily_campaigns(
        self,
        account_id: str,
        report_date: str,
    ) -> List[CampaignPerformanceRecord]:
        account = self._get(
            f"/act_{account_id}",
            params={
                "fields": "id,name,currency,timezone_name",
            },
        )
        insights = self._get(
            f"/act_{account_id}/insights",
            params={
                "fields": (
                    "account_id,account_name,"
                    "campaign_id,campaign_name,spend,impressions,clicks,actions,"
                    "date_start,date_stop"
                ),
                "time_range": json.dumps({"since": report_date, "until": report_date}),
                "level": "campaign",
                "limit": "500",
            },
        )

        fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        rows = insights.get("data", [])
        records: List[CampaignPerformanceRecord] = []
        for row in rows:
            spend = Decimal(str(row.get("spend", "0")))
            records.append(
                CampaignPerformanceRecord(
                    report_date=report_date,
                    platform="meta",
                    account_id=str(row.get("account_id") or account.get("id") or account_id),
                    account_name=str(row.get("account_name") or account.get("name") or ""),
                    campaign_id=str(row.get("campaign_id") or ""),
                    campaign_name=str(row.get("campaign_name") or ""),
                    currency=str(
                        account.get("currency")
                        or ""
                    ),
                    spend=spend,
                    impressions=int(str(row.get("impressions") or "0")),
                    clicks=int(str(row.get("clicks") or "0")),
                    conversions=self._sum_action_values(row.get("actions", [])),
                    timezone_name=str(account.get("timezone_name") or ""),
                    fetched_at=fetched_at,
                )
            )
        return records

    def validate_token(self) -> Dict[str, Any]:
        """Call /me to verify the token is valid. Returns the /me response."""
        return self._get("/me", params={"fields": "id,name"})

    def fetch_accessible_ad_accounts(self) -> List[Dict[str, str]]:
        rows = self._get_all(
            "/me/adaccounts",
            params={
                "fields": "id,account_id,name,timezone_name,currency,account_status,business",
                "limit": "200",
            },
        )
        accounts: List[Dict[str, str]] = []
        for row in rows:
            raw_identifier = str(row.get("account_id") or row.get("id") or "").strip()
            if not raw_identifier:
                continue
            business = row.get("business") if isinstance(row.get("business"), dict) else {}
            parent_account = str(business.get("name") or "").strip() or "-"
            accounts.append(
                {
                    "account_name": str(row.get("name") or raw_identifier).strip(),
                    "account_identifier": raw_identifier,
                    "timezone_name": str(row.get("timezone_name") or "Asia/Tokyo").strip(),
                    "parent_account": parent_account,
                    "currency": str(row.get("currency") or "").strip(),
                    "account_status": str(row.get("account_status") or "").strip(),
                }
            )
        return accounts

    def _sum_action_values(self, actions: Any) -> Decimal:
        total = Decimal("0")
        if not isinstance(actions, list):
            return total
        for action in actions:
            try:
                total += Decimal(str(action.get("value", "0")))
            except Exception:
                continue
        return total

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        merged_params = {
            **params,
            "access_token": self.access_token,
        }
        response = self.session.get(
            f"https://graph.facebook.com/{self.graph_api_version}{path}",
            params=merged_params,
            timeout=self.timeout_seconds,
        )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaApiError(
                f"Meta API returned non-JSON response with status {response.status_code}."
            ) from exc

        if response.status_code >= 400 or "error" in payload:
            error = payload.get("error", {})
            message = error.get("message") or str(payload)
            raise MetaApiError(message)

        return payload

    def _get_all(self, path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        merged_params = {
            **params,
            "access_token": self.access_token,
        }
        url = f"https://graph.facebook.com/{self.graph_api_version}{path}"
        rows: List[Dict[str, Any]] = []

        while url:
            response = self.session.get(
                url,
                params=merged_params if "?" not in url else None,
                timeout=self.timeout_seconds,
            )
            merged_params = None
            try:
                payload = response.json()
            except ValueError as exc:
                raise MetaApiError(
                    f"Meta API returned non-JSON response with status {response.status_code}."
                ) from exc
            if response.status_code >= 400 or "error" in payload:
                error = payload.get("error", {})
                message = error.get("message") or str(payload)
                raise MetaApiError(message)
            rows.extend(payload.get("data", []))
            paging = payload.get("paging", {})
            url = paging.get("next")

        return rows
