from __future__ import annotations


class ConfigError(ValueError):
    """Raised when required environment variables are missing."""


def normalize_account_id(account_id: str) -> str:
    normalized = account_id.strip()
    if normalized.startswith("act_"):
        return normalized[4:]
    return normalized
