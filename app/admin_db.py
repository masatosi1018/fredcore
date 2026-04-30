from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple


SUPPORTED_PLATFORMS = ("meta", "google", "tiktok")
DEFAULT_PLATFORM = "google"


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")


def extract_spreadsheet_id(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""

    patterns = [
        r"/spreadsheets/d/([a-zA-Z0-9-_]+)",
        r"[?&]id=([a-zA-Z0-9-_]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return value


class AdminRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.database_path))
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS credential_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    profile_identifier TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '正常',
                    auth_expiry TEXT,
                    auth_type TEXT NOT NULL DEFAULT 'manual',
                    external_user_id TEXT,
                    access_token TEXT,
                    refresh_token TEXT,
                    token_expires_at TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    creator_email TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS linked_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    account_name TEXT NOT NULL,
                    account_identifier TEXT NOT NULL,
                    timezone_name TEXT NOT NULL,
                    credential_profile_id INTEGER,
                    operator_email TEXT NOT NULL,
                    parent_account TEXT NOT NULL DEFAULT '-',
                    selection_source TEXT NOT NULL DEFAULT 'manual',
                    sync_enabled INTEGER NOT NULL DEFAULT 1,
                    sync_status TEXT NOT NULL DEFAULT '未同期',
                    last_synced_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (credential_profile_id) REFERENCES credential_profiles(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS integration_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS monthly_report_sheets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    month_key TEXT NOT NULL UNIQUE,
                    spreadsheet_id TEXT NOT NULL,
                    spreadsheet_url TEXT NOT NULL,
                    spreadsheet_title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '有効',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    rule_name TEXT NOT NULL,
                    target_label TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    condition_operator TEXT NOT NULL DEFAULT '>=',
                    threshold_value TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    action_value TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '有効',
                    owner_email TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    auth_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    code_verifier TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    trigger_source TEXT NOT NULL DEFAULT 'manual',
                    report_date TEXT NOT NULL,
                    month_key TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '実行中',
                    account_count INTEGER NOT NULL DEFAULT 0,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    updated_count INTEGER NOT NULL DEFAULT 0,
                    appended_count INTEGER NOT NULL DEFAULT 0,
                    spreadsheet_url TEXT NOT NULL DEFAULT '',
                    spreadsheet_title TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(
                connection,
                "credential_profiles",
                "auth_type",
                "TEXT NOT NULL DEFAULT 'manual'",
            )
            self._ensure_column(
                connection,
                "credential_profiles",
                "external_user_id",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "credential_profiles",
                "access_token",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "credential_profiles",
                "refresh_token",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "credential_profiles",
                "token_expires_at",
                "TEXT",
            )
            self._ensure_column(
                connection,
                "credential_profiles",
                "metadata_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                connection,
                "linked_accounts",
                "selection_source",
                "TEXT NOT NULL DEFAULT 'manual'",
            )
            self._ensure_column(
                connection,
                "linked_accounts",
                "sync_enabled",
                "INTEGER NOT NULL DEFAULT 1",
            )
            self._ensure_column(
                connection,
                "linked_accounts",
                "sync_status",
                "TEXT NOT NULL DEFAULT '未同期'",
            )
            self._ensure_column(
                connection,
                "linked_accounts",
                "last_synced_at",
                "TEXT",
            )

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        existing_columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing_columns:
            return
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )

    def seed_if_empty(self) -> None:
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT COUNT(*) AS count FROM credential_profiles"
            ).fetchone()["count"]
            if exists:
                return

            now = utc_now()
            credentials = [
                ("meta", "ながもと", "ryo.cip.fred@gmail.com", "正常", None, "daiki.sakai@fred-japan.co.jp", "2026-03-12 13:30", "2026-03-13 10:51"),
                ("google", "DYMFRED003", "dymfred003@gmail.com", "正常", None, "daiki.sakai@fred-japan.co.jp", "2026-04-01 16:40", "2026-04-06 19:23"),
                ("google", "OPT FRED", "optadfred001@gmail.com", "正常", None, "daiki.sakai@fred-japan.co.jp", "2026-03-10 15:49", "2026-03-10 15:49"),
                ("google", "OPT貸001", "optfred001@gmail.com", "正常", None, "daiki.sakai@fred-japan.co.jp", "2026-04-01 17:42", "2026-04-01 17:42"),
                ("google", "pmo001", "pmo001.fred.2026@gmail.com", "正常", None, "daiki.sakai@fred-japan.co.jp", "2026-03-15 10:07", "2026-03-15 10:07"),
                ("google", "yusuke2 chiba", "yusuke.chiba2@fred-japan.co.jp", "正常", None, "daiki.sakai@fred-japan.co.jp", "2026-03-27 18:31", "2026-04-06 19:15"),
                ("tiktok", "TikTok Main", "agency-growth@fred.jp", "正常", None, "daiki.sakai@fred-japan.co.jp", "2026-04-05 09:12", "2026-04-05 09:12"),
            ]
            connection.executemany(
                """
                INSERT INTO credential_profiles (
                    platform, profile_name, profile_identifier, status, auth_expiry,
                    auth_type, metadata_json, creator_email, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (*row[:5], "manual", "{}", *row[5:])
                    for row in credentials
                ],
            )

            profile_lookup = {
                row["profile_name"]: row["id"]
                for row in connection.execute(
                    "SELECT id, profile_name FROM credential_profiles"
                ).fetchall()
            }
            accounts = [
                ("google", "株式会社物販ONE08/fred", "4696494872", "Asia/Tokyo", profile_lookup["DYMFRED003"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
                ("google", "アズール株式会社09/fred", "1060984764", "Asia/Tokyo", profile_lookup["DYMFRED003"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
                ("google", "株式会社ミライラボラトリー05/fred", "6659927996", "Asia/Tokyo", profile_lookup["DYMFRED003"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
                ("google", "株式会社LADDER03/fred", "6276773654", "Asia/Tokyo", profile_lookup["DYMFRED003"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
                ("google", "アドネス株式会社08/fred", "5049084174", "Asia/Tokyo", profile_lookup["DYMFRED003"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
                ("google", "アズール株式会社08/fred", "1519429160", "Asia/Tokyo", profile_lookup["DYMFRED003"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
                ("google", "株式会社ミライラボラトリー06/fred", "1481105593", "Asia/Tokyo", profile_lookup["DYMFRED003"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
                ("google", "株式会社物販ONE09/fred", "1915293717", "Asia/Tokyo", profile_lookup["DYMFRED003"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
                ("google", "株式会社TOEZ12/fred", "9337704507", "Asia/Tokyo", profile_lookup["DYMFRED003"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
                ("meta", "fred_meta_main", "act_120011223344", "Asia/Tokyo", profile_lookup["ながもと"], "daiki.sakai@fred-japan.co.jp", "Fred Holdings", now, now),
                ("meta", "fred_meta_sub", "act_120011223355", "Asia/Tokyo", profile_lookup["ながもと"], "daiki.sakai@fred-japan.co.jp", "Fred Holdings", now, now),
                ("tiktok", "fred_tiktok_growth", "tt-77889911", "Asia/Tokyo", profile_lookup["TikTok Main"], "daiki.sakai@fred-japan.co.jp", "-", now, now),
            ]
            connection.executemany(
                """
                INSERT INTO linked_accounts (
                    platform, account_name, account_identifier, timezone_name,
                    credential_profile_id, operator_email, parent_account,
                    selection_source, sync_enabled, sync_status, last_synced_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (*row[:7], "manual", 1, "未同期", None, *row[7:])
                    for row in accounts
                ],
            )
            rules = [
                (
                    "meta",
                    "CPA 悪化時に Slack 通知",
                    "fred_meta_main",
                    "CPA",
                    ">=",
                    "8000",
                    "通知",
                    "Slack #ad-alerts",
                    "有効",
                    "daiki.sakai@fred-japan.co.jp",
                    "前日比で大きく悪化した時に担当者へ通知",
                    now,
                    now,
                ),
                (
                    "google",
                    "消化率 110% 超で入札調整",
                    "株式会社物販ONE08/fred",
                    "消化率",
                    ">=",
                    "110",
                    "入札調整",
                    "-15%",
                    "有効",
                    "daiki.sakai@fred-japan.co.jp",
                    "日予算を超えそうな時に抑制する想定",
                    now,
                    now,
                ),
                (
                    "tiktok",
                    "CTR 低下時に確認依頼",
                    "fred_tiktok_growth",
                    "CTR",
                    "<=",
                    "0.8",
                    "通知",
                    "運用担当へメール",
                    "停止中",
                    "daiki.sakai@fred-japan.co.jp",
                    "クリエイティブ差し替え判断用のたたき台",
                    now,
                    now,
                ),
            ]
            connection.executemany(
                """
                INSERT INTO automation_rules (
                    platform, rule_name, target_label, metric_name,
                    condition_operator, threshold_value, action_type, action_value,
                    status, owner_email, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rules,
            )

    def _platform_clause(
        self,
        platform: Optional[str],
        column_name: str = "platform",
    ) -> Tuple[str, List[str]]:
        if platform and platform in SUPPORTED_PLATFORMS:
            return f"WHERE {column_name} = ?", [platform]
        return "", []

    def get_platform_counts(self, table_name: str) -> Dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT platform, COUNT(*) AS count FROM {table_name} GROUP BY platform"
            ).fetchall()
        counts = {platform: 0 for platform in SUPPORTED_PLATFORMS}
        for row in rows:
            counts[row["platform"]] = row["count"]
        return counts

    def list_credentials(
        self,
        platform: Optional[str],
        query: str = "",
    ) -> List[sqlite3.Row]:
        clause, params = self._platform_clause(platform, "credential_profiles.platform")
        search = query.strip()
        search_clause = ""
        if search:
            search_clause = (
                " AND " if clause else " WHERE "
            ) + "(profile_name LIKE ? OR profile_identifier LIKE ? OR creator_email LIKE ?)"
            params.extend([f"%{search}%"] * 3)

        with self.connect() as connection:
            return connection.execute(
                f"""
                SELECT *
                FROM credential_profiles
                {clause}
                {search_clause}
                ORDER BY updated_at DESC, id DESC
                """,
                params,
            ).fetchall()

    def list_accounts(
        self,
        platform: Optional[str],
        query: str = "",
    ) -> List[sqlite3.Row]:
        clause, params = self._platform_clause(platform, "linked_accounts.platform")
        search = query.strip()
        search_clause = ""
        if search:
            search_clause = (
                " AND " if clause else " WHERE "
            ) + """
                (
                    linked_accounts.account_name LIKE ?
                    OR linked_accounts.account_identifier LIKE ?
                    OR linked_accounts.operator_email LIKE ?
                    OR credential_profiles.profile_name LIKE ?
                )
            """
            params.extend([f"%{search}%"] * 4)

        with self.connect() as connection:
            return connection.execute(
                f"""
                SELECT linked_accounts.*, credential_profiles.profile_name AS credential_profile_name
                FROM linked_accounts
                LEFT JOIN credential_profiles
                    ON linked_accounts.credential_profile_id = credential_profiles.id
                {clause}
                {search_clause}
                ORDER BY linked_accounts.account_name COLLATE NOCASE ASC
                """,
                params,
            ).fetchall()

    def credential_choices(self, platform: Optional[str] = None) -> List[sqlite3.Row]:
        clause, params = self._platform_clause(platform, "platform")
        with self.connect() as connection:
            return connection.execute(
                f"""
                SELECT id, profile_name, platform
                FROM credential_profiles
                {clause}
                ORDER BY profile_name COLLATE NOCASE ASC
                """,
                params,
            ).fetchall()

    def get_credential(self, credential_id: int) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT *
                FROM credential_profiles
                WHERE id = ?
                """,
                (credential_id,),
            ).fetchone()

    def list_rules(
        self,
        platform: Optional[str],
        query: str = "",
    ) -> List[sqlite3.Row]:
        clause, params = self._platform_clause(platform, "platform")
        search = query.strip()
        search_clause = ""
        if search:
            search_clause = (
                " AND " if clause else " WHERE "
            ) + """
                (
                    rule_name LIKE ?
                    OR target_label LIKE ?
                    OR metric_name LIKE ?
                    OR action_type LIKE ?
                    OR action_value LIKE ?
                    OR owner_email LIKE ?
                )
            """
            params.extend([f"%{search}%"] * 6)

        with self.connect() as connection:
            return connection.execute(
                f"""
                SELECT *
                FROM automation_rules
                {clause}
                {search_clause}
                ORDER BY updated_at DESC, rule_name COLLATE NOCASE ASC
                """,
                params,
            ).fetchall()

    def create_credential(
        self,
        platform: str,
        profile_name: str,
        profile_identifier: str,
        creator_email: str,
        auth_expiry: str,
        *,
        auth_type: str = "manual",
        external_user_id: str = "",
        access_token: str = "",
        refresh_token: str = "",
        token_expires_at: str = "",
        metadata_json: str = "{}",
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO credential_profiles (
                    platform, profile_name, profile_identifier, status, auth_expiry,
                    auth_type, external_user_id, access_token, refresh_token,
                    token_expires_at, metadata_json, creator_email, created_at, updated_at
                ) VALUES (?, ?, ?, '正常', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    profile_name,
                    profile_identifier,
                    auth_expiry or None,
                    auth_type,
                    external_user_id or None,
                    access_token or None,
                    refresh_token or None,
                    token_expires_at or None,
                    metadata_json or "{}",
                    creator_email,
                    now,
                    now,
                ),
            )

    def create_account(
        self,
        platform: str,
        account_name: str,
        account_identifier: str,
        timezone_name: str,
        credential_profile_id: Optional[int],
        operator_email: str,
        parent_account: str,
        *,
        selection_source: str = "manual",
        sync_enabled: bool = True,
        sync_status: str = "未同期",
        last_synced_at: str = "",
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO linked_accounts (
                    platform, account_name, account_identifier, timezone_name,
                    credential_profile_id, operator_email, parent_account,
                    selection_source, sync_enabled, sync_status, last_synced_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    account_name,
                    account_identifier,
                    timezone_name,
                    credential_profile_id,
                    operator_email,
                    parent_account or "-",
                    selection_source or "manual",
                    1 if sync_enabled else 0,
                    sync_status or "未同期",
                    last_synced_at or None,
                    now,
                    now,
                ),
            )

    def create_rule(
        self,
        *,
        platform: str,
        rule_name: str,
        target_label: str,
        metric_name: str,
        condition_operator: str,
        threshold_value: str,
        action_type: str,
        action_value: str,
        status: str,
        owner_email: str,
        notes: str = "",
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO automation_rules (
                    platform, rule_name, target_label, metric_name,
                    condition_operator, threshold_value, action_type, action_value,
                    status, owner_email, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    platform,
                    rule_name.strip(),
                    target_label.strip(),
                    metric_name.strip(),
                    condition_operator.strip() or ">=",
                    threshold_value.strip(),
                    action_type.strip(),
                    action_value.strip(),
                    status.strip() or "有効",
                    owner_email.strip(),
                    notes.strip(),
                    now,
                    now,
                ),
            )

    def reauth_credential(self, credential_id: int) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE credential_profiles
                SET status = '正常', updated_at = ?
                WHERE id = ?
                """,
                (now, credential_id),
            )

    def delete_credential(self, credential_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE linked_accounts SET credential_profile_id = NULL WHERE credential_profile_id = ?",
                (credential_id,),
            )
            connection.execute(
                "DELETE FROM credential_profiles WHERE id = ?",
                (credential_id,),
            )

    def delete_account(self, account_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM linked_accounts WHERE id = ?",
                (account_id,),
            )

    def delete_rule(self, rule_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM automation_rules WHERE id = ?",
                (rule_id,),
            )

    def create_oauth_state(
        self,
        *,
        state: str,
        platform: str,
        auth_type: str,
        payload_json: str,
        code_verifier: str = "",
        expires_at: str,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_states (
                    state, platform, auth_type, payload_json, code_verifier,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state,
                    platform,
                    auth_type,
                    payload_json,
                    code_verifier,
                    now,
                    expires_at,
                ),
            )

    def consume_oauth_state(self, state: str) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM oauth_states
                WHERE state = ?
                """,
                (state,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "DELETE FROM oauth_states WHERE state = ?",
                (state,),
            )
            return row

    def list_monthly_report_sheets(self) -> List[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT *
                FROM monthly_report_sheets
                ORDER BY month_key DESC, id DESC
                """
            ).fetchall()

    def get_monthly_report_sheet(self, month_key: str) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT *
                FROM monthly_report_sheets
                WHERE month_key = ?
                """,
                (month_key.strip(),),
            ).fetchone()

    def save_monthly_report_sheet(
        self,
        *,
        month_key: str,
        spreadsheet_url: str,
        spreadsheet_title: str,
        status: str = "有効",
        notes: str = "",
    ) -> None:
        now = utc_now()
        normalized_month_key = month_key.strip()
        normalized_url = spreadsheet_url.strip()
        spreadsheet_id = extract_spreadsheet_id(normalized_url)

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO monthly_report_sheets (
                    month_key, spreadsheet_id, spreadsheet_url, spreadsheet_title,
                    status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(month_key) DO UPDATE SET
                    spreadsheet_id = excluded.spreadsheet_id,
                    spreadsheet_url = excluded.spreadsheet_url,
                    spreadsheet_title = excluded.spreadsheet_title,
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_month_key,
                    spreadsheet_id,
                    normalized_url,
                    spreadsheet_title.strip(),
                    status.strip() or "有効",
                    notes.strip(),
                    now,
                    now,
                ),
            )

    def delete_monthly_report_sheet(self, sheet_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM monthly_report_sheets WHERE id = ?",
                (sheet_id,),
            )

    def create_sync_run(
        self,
        *,
        job_name: str,
        platform: str,
        trigger_source: str,
        report_date: str,
        month_key: str,
    ) -> int:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO sync_runs (
                    job_name, platform, trigger_source, report_date, month_key, status,
                    started_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, '実行中', ?, ?, ?)
                """,
                (
                    job_name,
                    platform,
                    trigger_source,
                    report_date,
                    month_key,
                    now,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def complete_sync_run(
        self,
        sync_run_id: int,
        *,
        status: str,
        account_count: int = 0,
        row_count: int = 0,
        updated_count: int = 0,
        appended_count: int = 0,
        spreadsheet_url: str = "",
        spreadsheet_title: str = "",
        error_message: str = "",
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                SET status = ?,
                    account_count = ?,
                    row_count = ?,
                    updated_count = ?,
                    appended_count = ?,
                    spreadsheet_url = ?,
                    spreadsheet_title = ?,
                    error_message = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    account_count,
                    row_count,
                    updated_count,
                    appended_count,
                    spreadsheet_url,
                    spreadsheet_title,
                    error_message,
                    now,
                    now,
                    sync_run_id,
                ),
            )

    def list_sync_runs(self, limit: int = 100) -> List[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT *
                FROM sync_runs
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def get_integration_settings(self) -> Dict[str, str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT key, value FROM integration_settings"
            ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def save_integration_settings(self, settings: Dict[str, str]) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO integration_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                [(key, value, now) for key, value in settings.items()],
            )
