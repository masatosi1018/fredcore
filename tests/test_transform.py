import unittest
from decimal import Decimal

from app.models import CampaignPerformanceRecord, DailySpendRecord
from app.transform import (
    build_campaign_report_row,
    build_sheet_row,
    campaign_row_key_from_values,
    compose_campaign_row_key,
    compose_row_key,
    decimal_to_sheet_value,
)


class TransformTest(unittest.TestCase):
    def test_compose_row_key(self):
        self.assertEqual(compose_row_key("2026-04-20", "123"), "2026-04-20::123")

    def test_decimal_format(self):
        self.assertEqual(decimal_to_sheet_value(Decimal("123.456")), "123.46")

    def test_build_sheet_row(self):
        row = build_sheet_row(
            DailySpendRecord(
                report_date="2026-04-20",
                account_id="123",
                account_name="Main Account",
                currency="JPY",
                spend=Decimal("456.7"),
                timezone_name="Asia/Tokyo",
                fetched_at="2026-04-21T00:00:00+00:00",
            )
        )
        self.assertEqual(
            row,
            [
                "2026-04-20",
                "123",
                "Main Account",
                "JPY",
                "456.70",
                "Asia/Tokyo",
                "2026-04-21T00:00:00+00:00",
                "meta_marketing_api",
            ],
        )

    def test_compose_campaign_row_key(self):
        self.assertEqual(
            compose_campaign_row_key("2026-04-20", "meta", "123", "456"),
            "2026-04-20::meta::123::456",
        )

    def test_build_campaign_report_row(self):
        row = build_campaign_report_row(
            CampaignPerformanceRecord(
                report_date="2026-04-20",
                platform="meta",
                account_id="123",
                account_name="Main Account",
                campaign_id="456",
                campaign_name="Campaign A",
                currency="JPY",
                spend=Decimal("456.7"),
                impressions=1000,
                clicks=22,
                conversions=Decimal("3"),
                timezone_name="Asia/Tokyo",
                fetched_at="2026-04-21T00:00:00+00:00",
            )
        )
        self.assertEqual(
            row,
            [
                "2026-04-20",
                "meta",
                "123",
                "Main Account",
                "456",
                "Campaign A",
                "JPY",
                "456.70",
                "1000",
                "22",
                "3.00",
                "Asia/Tokyo",
                "2026-04-21T00:00:00+00:00",
                "meta_marketing_api",
            ],
        )

    def test_campaign_row_key_from_values(self):
        self.assertEqual(
            campaign_row_key_from_values(
                ["2026-04-20", "meta", "123", "Main", "456", "Campaign A"]
            ),
            "2026-04-20::meta::123::456",
        )


if __name__ == "__main__":
    unittest.main()
