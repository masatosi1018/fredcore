from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, Union

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional in sqlite-only environments
    psycopg = None
    dict_row = None


SUPPORTED_PLATFORMS = ("meta", "google", "tiktok")
DEFAULT_PLATFORM = "google"
LEGACY_DEMO_CREDENTIAL_IDENTIFIERS = (
    "ryo.cip.fred@gmail.com",
    "dymfred003@gmail.com",
    "optadfred001@gmail.com",
    "optfred001@gmail.com",
    "pmo001.fred.2026@gmail.com",
    "yusuke.chiba2@fred-japan.co.jp",
    "agency-growth@fred.jp",
)
LEGACY_DEMO_ACCOUNT_IDENTIFIERS = (
    "4696494872",
    "1060984764",
    "6659927996",
    "6276773654",
    "5049084174",
    "1519429160",
    "1481105593",
    "1915293717",
    "9337704507",
    "act_120011223344",
    "act_120011223355",
    "tt-77889911",
)
LEGACY_DEMO_RULE_NAMES = (
    "CPA 悪化時に Slack 通知",
    "消化率 110% 超で入札調整",
    "CTR 低下時に確認依頼",
)


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
    def __init__(self, database_target: Union[Path, str]):
        target = str(database_target)
        self.database_url = target.strip() if self._is_postgres_dsn(target) else ""
        self.database_path = (
            None
            if self.database_url
            else Path(database_target)
        )
        if self.database_path is not None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_postgres_dsn(value: str) -> bool:
        normalized = value.strip().lower()
        return normalized.startswith("postgres://") or normalized.startswith("postgresql://")

    @property
    def backend(self) -> str:
        return "postgres" if self.database_url else "sqlite"

    def _translate_sql(self, sql: str) -> str:
        if self.backend != "postgres":
            return sql
        return sql.replace("?", "%s")

    def _connect_postgres(self):
        if psycopg is None:
            raise RuntimeError(
                "Postgres を使うには psycopg が必要です。requirements.txt を再インストールしてください。"
            )
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self.backend == "postgres":
            connection = self._connect_postgres()
        else:
            connection = sqlite3.connect(str(self.database_path))
            connection.row_factory = sqlite3.Row
        try:
            yield _ConnectionAdapter(connection, self.backend, self._translate_sql)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            for statement in self._create_table_statements():
                connection.execute(statement)
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
            self._ensure_column(
                connection,
                "linked_accounts",
                "last_synced_report_date",
                "TEXT",
            )

    def _create_table_statements(self) -> List[str]:
        if self.backend == "postgres":
            id_column = "BIGSERIAL PRIMARY KEY"
        else:
            id_column = "INTEGER PRIMARY KEY AUTOINCREMENT"
        return [
            f"""
            CREATE TABLE IF NOT EXISTS credential_profiles (
                id {id_column},
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
                metadata_json TEXT NOT NULL DEFAULT '{{}}',
                creator_email TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS linked_accounts (
                id {id_column},
                platform TEXT NOT NULL,
                account_name TEXT NOT NULL,
                account_identifier TEXT NOT NULL,
                timezone_name TEXT NOT NULL,
                credential_profile_id BIGINT,
                operator_email TEXT NOT NULL,
                parent_account TEXT NOT NULL DEFAULT '-',
                selection_source TEXT NOT NULL DEFAULT 'manual',
                sync_enabled INTEGER NOT NULL DEFAULT 1,
                sync_status TEXT NOT NULL DEFAULT '未同期',
                last_synced_at TEXT,
                last_synced_report_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (credential_profile_id) REFERENCES credential_profiles(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS integration_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS monthly_report_sheets (
                id {id_column},
                month_key TEXT NOT NULL UNIQUE,
                spreadsheet_id TEXT NOT NULL,
                spreadsheet_url TEXT NOT NULL,
                spreadsheet_title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '有効',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS automation_rules (
                id {id_column},
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
            """,
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
            """,
            f"""
            CREATE TABLE IF NOT EXISTS sync_runs (
                id {id_column},
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
            """,
        ]

    def _ensure_column(
        self,
        connection: Any,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        if self.backend == "postgres":
            existing_columns = {
                row["column_name"]
                for row in connection.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = ?
                    """,
                    (table_name,),
                ).fetchall()
            }
        else:
            existing_columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
        if column_name in existing_columns:
            return
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )

    def cleanup_legacy_demo_data(self) -> None:
        with self.connect() as connection:
            self._delete_rows_by_values(
                connection,
                "automation_rules",
                "rule_name",
                LEGACY_DEMO_RULE_NAMES,
            )
            self._delete_rows_by_values(
                connection,
                "linked_accounts",
                "account_identifier",
                LEGACY_DEMO_ACCOUNT_IDENTIFIERS,
            )
            self._delete_rows_by_values(
                connection,
                "credential_profiles",
                "profile_identifier",
                LEGACY_DEMO_CREDENTIAL_IDENTIFIERS,
            )

    def _delete_rows_by_values(
        self,
        connection: Any,
        table_name: str,
        column_name: str,
        values: Iterable[str],
    ) -> None:
        normalized_values = [value for value in values if value]
        if not normalized_values:
            return
        placeholders = ", ".join("?" for _ in normalized_values)
        connection.execute(
            f"DELETE FROM {table_name} WHERE {column_name} IN ({placeholders})",
            tuple(normalized_values),
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
                ORDER BY LOWER(linked_accounts.account_name) ASC, linked_accounts.account_name ASC
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
                ORDER BY LOWER(profile_name) ASC, profile_name ASC
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
                ORDER BY updated_at DESC, LOWER(rule_name) ASC, rule_name ASC
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
        last_synced_report_date: str = "",
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO linked_accounts (
                    platform, account_name, account_identifier, timezone_name,
                    credential_profile_id, operator_email, parent_account,
                    selection_source, sync_enabled, sync_status, last_synced_at,
                    last_synced_report_date,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    last_synced_report_date or None,
                    now,
                    now,
                ),
            )

    def update_account_sync_state(
        self,
        account_id: int,
        *,
        sync_status: str,
        last_synced_at: str = "",
        last_synced_report_date: str = "",
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE linked_accounts
                SET sync_status = ?,
                    last_synced_at = ?,
                    last_synced_report_date = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    sync_status.strip() or "未同期",
                    last_synced_at or None,
                    last_synced_report_date or None,
                    now,
                    account_id,
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
            if self.backend == "postgres":
                row = connection.execute(
                    """
                    INSERT INTO sync_runs (
                        job_name, platform, trigger_source, report_date, month_key, status,
                        started_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, '実行中', ?, ?, ?)
                    RETURNING id
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
                ).fetchone()
                return int(row["id"])
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


class _ConnectionAdapter:
    def __init__(self, connection: Any, backend: str, translator):
        self._connection = connection
        self.backend = backend
        self._translator = translator

    def execute(self, sql: str, params: Iterable[Any] = ()):
        translated_sql = self._translator(sql)
        if hasattr(self._connection, "execute"):
            return self._connection.execute(translated_sql, params)
        cursor = self._connection.cursor()
        cursor.execute(translated_sql, params)
        return cursor

    def executemany(self, sql: str, seq_of_params):
        translated_sql = self._translator(sql)
        if hasattr(self._connection, "executemany"):
            return self._connection.executemany(translated_sql, seq_of_params)
        cursor = self._connection.cursor()
        cursor.executemany(translated_sql, seq_of_params)
        return cursor
