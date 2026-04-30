from __future__ import annotations

import argparse
import json
from typing import List, Tuple

from app.config import ConfigError, Settings
from app.dates import iso_date, parse_target_date
from app.meta_api import MetaClient
from app.sheets import GoogleSheetsClient
from app.transform import build_sheet_row, compose_row_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch daily Meta ad spend and sync it to Google Sheets."
    )
    parser.add_argument(
        "--date",
        dest="report_date",
        help="Report date in YYYY-MM-DD. Defaults to yesterday in REPORT_TIMEZONE.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch the data but do not write to Google Sheets.",
    )
    return parser.parse_args()


def collect_rows(settings: Settings, report_date: str) -> List[Tuple[str, List[str]]]:
    client = MetaClient(
        access_token=settings.meta_access_token,
        graph_api_version=settings.meta_graph_api_version,
        timeout_seconds=settings.meta_request_timeout_seconds,
    )
    keyed_rows = []

    for account_id in settings.meta_ad_account_ids:
        record = client.fetch_account_daily_spend(account_id=account_id, report_date=report_date)
        if not settings.include_zero_spend_rows and record.spend == 0:
            continue

        row = build_sheet_row(record)
        key = compose_row_key(record.report_date, record.account_id)
        keyed_rows.append((key, row))

    return keyed_rows


def main() -> int:
    args = parse_args()

    try:
        settings = Settings.from_env()
        report_date = iso_date(parse_target_date(args.report_date, settings.report_timezone))
    except (ConfigError, ValueError) as exc:
        print(f"Configuration error: {exc}")
        return 1

    try:
        keyed_rows = collect_rows(settings, report_date)
    except Exception as exc:
        print(f"Meta fetch failed: {exc}")
        return 1

    if args.dry_run:
        print(json.dumps({"report_date": report_date, "rows": [row for _, row in keyed_rows]}, ensure_ascii=False, indent=2))
        return 0

    try:
        sheets = GoogleSheetsClient(
            service_account_file=str(settings.google_service_account_file),
            spreadsheet_id=settings.google_spreadsheet_id,
            sheet_name=settings.google_sheet_name,
        )
        sheets.ensure_header()
        updated_count, appended_count = sheets.upsert_rows(keyed_rows)
    except Exception as exc:
        print(f"Google Sheets sync failed: {exc}")
        return 1

    print(
        json.dumps(
            {
                "report_date": report_date,
                "accounts": len(keyed_rows),
                "updated": updated_count,
                "appended": appended_count,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
