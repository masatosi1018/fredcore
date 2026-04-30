from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional


def _resolve_timezone(timezone_name: Optional[str]):
    if not timezone_name:
        return datetime.now().astimezone().tzinfo

    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(timezone_name)
    except ImportError:
        try:
            from backports.zoneinfo import ZoneInfo

            return ZoneInfo(timezone_name)
        except ImportError:
            return datetime.now().astimezone().tzinfo


def default_target_date(timezone_name: Optional[str]) -> date:
    tzinfo = _resolve_timezone(timezone_name)
    return (datetime.now(tz=tzinfo) - timedelta(days=1)).date()


def parse_target_date(raw_value: Optional[str], timezone_name: Optional[str]) -> date:
    if raw_value:
        return date.fromisoformat(raw_value)
    return default_target_date(timezone_name)


def iso_date(value: date) -> str:
    return value.isoformat()
