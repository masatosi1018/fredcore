from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional
from urllib.parse import parse_qs, urlencode
from wsgiref.simple_server import make_server
from wsgiref.util import setup_testing_defaults

from app.account_linking import find_discoverable_accounts, list_discoverable_accounts
from app.admin_db import AdminRepository, DEFAULT_PLATFORM, SUPPORTED_PLATFORMS
from app.config import ConfigError
from app.dates import default_target_date
from app.meta_api import MetaApiError, MetaClient
from app.meta_sync import INTEGRATION_DEFAULTS, MetaSheetSyncConfig, sync_meta_accounts_to_sheet
from app.oauth_clients import (
    OAuthError,
    build_google_authorization_url,
    build_meta_authorization_url,
    create_oauth_state,
    exchange_google_code,
    exchange_meta_code,
    fetch_google_profile,
    fetch_meta_profile,
    google_oauth_config,
    meta_oauth_config,
    metadata_json_for_oauth,
)
from app.campaign_sync import sync_meta_campaigns_to_monthly_sheet
from app.report_sheets import ensure_monthly_report_sheet
from app.sync_jobs import run_meta_monthly_sync_job
from app.sync_jobs import run_meta_daily_sync_job
from app.admin_views import (
    render_accounts_page,
    render_credentials_page,
    render_report_sheet_form,
    render_report_sheets_page,
    render_settings_page,
    render_sync_runs_page,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"
_REPOSITORY_READY = False


def resolve_database_target(project_root: Path):
    database_url = (
        os.environ.get("FREDCORE_DATABASE_URL", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
        or os.environ.get("POSTGRES_URL", "").strip()
    )
    if database_url:
        return database_url
    configured_path = os.environ.get("FREDCORE_DATABASE_PATH", "").strip()
    if configured_path:
        database_path = Path(configured_path)
        return database_path if database_path.is_absolute() else project_root / database_path
    if os.environ.get("VERCEL") == "1":
        return Path("/tmp/fredcore.db")
    return project_root / "data" / "fredcore.db"


DATABASE_TARGET = resolve_database_target(PROJECT_ROOT)
REPOSITORY = AdminRepository(DATABASE_TARGET)
MONTH_KEY_PATTERN = re.compile(r"^\d{4}-\d{2}$")
WATCHED_DIRECTORIES = ("app", "static", "config", "tests")
WATCHED_FILES = ("README.md", "requirements.txt", ".env.example")
IGNORED_DIRECTORY_NAMES = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache"}
WATCHED_SUFFIXES = {".py", ".css", ".js", ".html", ".txt", ".md", ".json", ".png", ".svg"}
RELOAD_POLL_SECONDS = 1.0


def ensure_repository_ready() -> None:
    global _REPOSITORY_READY
    if _REPOSITORY_READY:
        return
    REPOSITORY.initialize()
    REPOSITORY.seed_if_empty()
    _REPOSITORY_READY = True


def parse_form(environ) -> dict:
    try:
        size = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        size = 0
    raw_body = environ["wsgi.input"].read(size).decode("utf-8")
    parsed = parse_qs(raw_body)
    return {key: values[0] for key, values in parsed.items()}


def query_param(environ, name: str, default: str = "") -> str:
    parsed = parse_qs(environ.get("QUERY_STRING", ""))
    return parsed.get(name, [default])[0]


def redirect_to(start_response, path: str, **params):
    clean_params = {key: value for key, value in params.items() if value not in ("", None)}
    location = path
    if clean_params:
        location = f"{path}?{urlencode(clean_params)}"
    return redirect(start_response, location)


def active_platform(environ) -> str:
    platform = query_param(environ, "platform", DEFAULT_PLATFORM)
    if platform not in SUPPORTED_PLATFORMS:
        return DEFAULT_PLATFORM
    return platform


def redirect(start_response, location: str):
    start_response("303 See Other", [("Location", location)])
    return [b""]


def respond_html(start_response, body: bytes, status: str = "200 OK"):
    headers = [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    start_response(status, headers)
    return [body]


def respond_json(start_response, payload: dict, status: str = "200 OK"):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    start_response(status, headers)
    return [body]


def serve_static(path: str, start_response):
    relative_path = path[len("/static/") :] if path.startswith("/static/") else path
    file_path = STATIC_DIR / relative_path
    if not file_path.exists() or not file_path.is_file():
        return respond_html(start_response, b"Not Found", "404 Not Found")

    body = file_path.read_bytes()
    content_type, _ = mimetypes.guess_type(str(file_path))
    start_response(
        "200 OK",
        [
            ("Content-Type", content_type or "application/octet-stream"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def should_watch_path(path: Path) -> bool:
    if any(part in IGNORED_DIRECTORY_NAMES for part in path.parts):
        return False
    if path.is_dir():
        return False
    if path.name in WATCHED_FILES:
        return True
    return path.suffix.lower() in WATCHED_SUFFIXES


def iter_watched_paths(project_root: Path) -> Iterable[Path]:
    seen = set()
    for relative_dir in WATCHED_DIRECTORIES:
        directory = project_root / relative_dir
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path in seen:
                continue
            if should_watch_path(path):
                seen.add(path)
                yield path
    for filename in WATCHED_FILES:
        path = project_root / filename
        if path.exists() and path not in seen and should_watch_path(path):
            seen.add(path)
            yield path


def snapshot_watched_files(project_root: Path) -> Dict[str, int]:
    snapshot = {}
    for path in iter_watched_paths(project_root):
        try:
            snapshot[str(path)] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return snapshot


def detect_changed_paths(previous: Dict[str, int], current: Dict[str, int]):
    changes = []
    for path, mtime in current.items():
        if previous.get(path) != mtime:
            changes.append(path)
    for path in previous:
        if path not in current:
            changes.append(path)
    return sorted(changes)


def run_with_reloader() -> int:
    child_env = os.environ.copy()
    child_env["FREDCORE_RUN_MAIN"] = "1"
    command = [sys.executable, "-m", "app.dashboard"]
    snapshot = snapshot_watched_files(PROJECT_ROOT)

    while True:
        child = subprocess.Popen(command, cwd=str(PROJECT_ROOT), env=child_env)
        should_restart = False
        try:
            while child.poll() is None:
                time.sleep(RELOAD_POLL_SECONDS)
                current_snapshot = snapshot_watched_files(PROJECT_ROOT)
                changed_paths = detect_changed_paths(snapshot, current_snapshot)
                if not changed_paths:
                    continue
                snapshot = current_snapshot
                print(f"Detected change, reloading server: {changed_paths[0]}")
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                should_restart = True
                break
        except KeyboardInterrupt:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            return 0

        if should_restart:
            continue
        if child.returncode is None:
            return 0
        if child.returncode != 0:
            return child.returncode
        return 0


def render_accounts_response(
    start_response,
    *,
    platform: str,
    query: str = "",
    report_date: str = "",
    notice: str = "",
    error: str = "",
    status: str = "200 OK",
    modal_state: Optional[dict] = None,
):
    integration_settings = REPOSITORY.get_integration_settings()
    sync_date = report_date or default_target_date(
        integration_settings.get(
            "report_timezone",
            INTEGRATION_DEFAULTS["report_timezone"],
        )
    ).isoformat()
    body = render_accounts_page(
        REPOSITORY.list_accounts(platform, query),
        REPOSITORY.get_platform_counts("linked_accounts"),
        platform,
        query,
        notice=notice,
        error=error,
        sync_settings=integration_settings,
        sync_date=sync_date,
        credential_rows=REPOSITORY.list_credentials(None),
        linked_account_rows=REPOSITORY.list_accounts(None),
        account_link_modal_state=modal_state,
    )
    return respond_html(start_response, body, status)


def render_credentials_response(
    start_response,
    *,
    platform: str,
    query: str = "",
    notice: str = "",
    error: str = "",
    status: str = "200 OK",
    modal_state: Optional[dict] = None,
):
    body = render_credentials_page(
        REPOSITORY.list_credentials(platform, query),
        REPOSITORY.get_platform_counts("credential_profiles"),
        platform,
        query,
        notice=notice,
        error=error,
        credential_modal_state=modal_state,
    )
    return respond_html(start_response, body, status)


def start_credential_oauth_flow(form: dict):
    settings = REPOSITORY.get_integration_settings()
    platform = form["platform"].strip()
    auth_type = form.get("auth_type", "manual").strip() or "manual"
    payload = {
        "platform": platform,
        "auth_type": auth_type,
        "profile_name": form.get("profile_name", "").strip(),
        "profile_identifier": form.get("profile_identifier", "").strip(),
        "creator_email": form.get("creator_email", "").strip(),
        "auth_expiry": form.get("auth_expiry", "").strip(),
        "external_user_id": form.get("external_user_id", "").strip(),
        "token_expires_at": form.get("token_expires_at", "").strip(),
    }
    state = create_oauth_state()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(microsecond=0).isoformat()

    if platform == "google":
        config = google_oauth_config(settings)
        code_verifier = create_oauth_state()
        REPOSITORY.create_oauth_state(
            state=state,
            platform=platform,
            auth_type=auth_type,
            payload_json=json.dumps(payload, ensure_ascii=False),
            code_verifier=code_verifier,
            expires_at=expires_at,
        )
        return build_google_authorization_url(config, state=state, code_verifier=code_verifier)

    if platform == "meta":
        config = meta_oauth_config(settings)
        REPOSITORY.create_oauth_state(
            state=state,
            platform=platform,
            auth_type=auth_type,
            payload_json=json.dumps(payload, ensure_ascii=False),
            code_verifier="",
            expires_at=expires_at,
        )
        return build_meta_authorization_url(config, state=state)

    raise OAuthError("このプラットフォームでは OAuth 連携はまだ利用できません。")


def complete_credential_oauth(platform: str, *, state: str, code: str) -> str:
    state_row = REPOSITORY.consume_oauth_state(state)
    if state_row is None:
        raise OAuthError("OAuth セッションが見つかりません。もう一度やり直してください。")

    expires_at = str(state_row["expires_at"] or "").strip()
    if expires_at:
        try:
            expires_at_dt = datetime.fromisoformat(expires_at)
        except ValueError:
            expires_at_dt = None
        if expires_at_dt is not None and expires_at_dt < datetime.now(timezone.utc):
            raise OAuthError("OAuth セッションの有効期限が切れました。もう一度やり直してください。")

    settings = REPOSITORY.get_integration_settings()
    payload = json.loads(state_row["payload_json"])
    if platform == "google":
        config = google_oauth_config(settings)
        token = exchange_google_code(
            config,
            code=code,
            code_verifier=str(state_row["code_verifier"] or ""),
        )
        profile = fetch_google_profile(token)
    elif platform == "meta":
        config = meta_oauth_config(settings)
        token = exchange_meta_code(config, code=code)
        profile = fetch_meta_profile(config, token)
    else:
        raise OAuthError("未対応の OAuth プラットフォームです。")

    profile_name = str(payload.get("profile_name") or profile.profile_name).strip()
    profile_identifier = str(payload.get("profile_identifier") or profile.profile_identifier).strip()
    creator_email = str(payload.get("creator_email") or "").strip()
    auth_expiry = token.token_expires_at or str(payload.get("auth_expiry") or "").strip()

    if not creator_email:
        raise OAuthError("作成者メールが未指定です。")

    REPOSITORY.create_credential(
        platform=platform,
        profile_name=profile_name,
        profile_identifier=profile_identifier,
        creator_email=creator_email,
        auth_expiry=auth_expiry,
        auth_type=str(state_row["auth_type"] or "oauth"),
        external_user_id=profile.external_user_id,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        token_expires_at=token.token_expires_at,
        metadata_json=metadata_json_for_oauth(
            platform=platform,
            auth_type=str(state_row["auth_type"] or "oauth"),
            profile=profile,
            token=token,
        ),
    )
    return profile_name or profile.profile_name


def fetch_linkable_accounts(
    *,
    platform: str,
    credential_profile_id: int,
):
    if platform != "meta":
        raise ConfigError("このプラットフォームの実アカウント取得はまだ未対応です。")

    credential = REPOSITORY.get_credential(credential_profile_id)
    if credential is None or credential["platform"] != platform:
        raise ConfigError("認証プロフィールが見つかりません。")
    access_token = str(credential["access_token"] or "").strip()
    if not access_token:
        raise ConfigError("この認証プロフィールには Meta のアクセストークンが保存されていません。")

    settings = REPOSITORY.get_integration_settings()
    graph_api_version = settings.get("meta_graph_api_version", "").strip() or "v22.0"
    timeout_seconds = int(settings.get("meta_request_timeout_seconds", "30").strip() or "30")
    client = MetaClient(
        access_token=access_token,
        graph_api_version=graph_api_version,
        timeout_seconds=timeout_seconds,
    )
    accounts = client.fetch_accessible_ad_accounts()
    if not accounts:
        raise ConfigError("Meta から連携可能な広告アカウントを取得できませんでした。")
    return {
        "credential_profile_name": str(credential["profile_name"] or ""),
        "accounts": accounts,
    }


def application(environ, start_response):
    setup_testing_defaults(environ)
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    platform = active_platform(environ)
    query = query_param(environ, "q", "")
    notice = query_param(environ, "notice", "")
    error = query_param(environ, "error", "")

    try:
        ensure_repository_ready()
    except Exception as exc:
        traceback.print_exc()
        if path == "/api/health" and method == "GET":
            return respond_json(
                start_response,
                {
                    "ok": False,
                    "database_backend": REPOSITORY.backend,
                    "error": str(exc),
                },
                "500 Internal Server Error",
            )
        return respond_html(
            start_response,
            f"Internal Server Error: {exc}".encode("utf-8"),
            "500 Internal Server Error",
        )

    if path.startswith("/static/"):
        return serve_static(path, start_response)

    if path == "/":
        return redirect(start_response, f"/accounts?platform={platform}")

    if path == "/api/health" and method == "GET":
        return respond_json(
            start_response,
            {
                "ok": True,
                "database_backend": REPOSITORY.backend,
                "app_base_url": (
                    REPOSITORY.get_integration_settings().get("app_base_url", "").strip()
                    or os.environ.get("FREDCORE_APP_BASE_URL", "").strip()
                ),
            },
        )

    if path == "/api/account-candidates" and method == "GET":
        requested_platform = query_param(environ, "platform", platform).strip() or platform
        credential_profile_id = query_param(environ, "credential_profile_id", "").strip()
        if requested_platform not in SUPPORTED_PLATFORMS:
            return respond_json(
                start_response,
                {"ok": False, "error": "連携対象のプラットフォームが不正です。"},
                "400 Bad Request",
            )
        if requested_platform != "meta":
            return respond_json(
                start_response,
                {
                    "ok": True,
                    "credential_profile_name": "",
                    "accounts": list_discoverable_accounts(requested_platform),
                },
            )
        if not credential_profile_id.isdigit():
            return respond_json(
                start_response,
                {"ok": False, "error": "Meta の認証プロフィールを選択してください。"},
                "400 Bad Request",
            )
        try:
            payload = fetch_linkable_accounts(
                platform=requested_platform,
                credential_profile_id=int(credential_profile_id),
            )
        except (ConfigError, MetaApiError, ValueError) as exc:
            return respond_json(
                start_response,
                {"ok": False, "error": str(exc)},
                "400 Bad Request",
            )
        return respond_json(
            start_response,
            {
                "ok": True,
                "credential_profile_name": payload["credential_profile_name"],
                "accounts": payload["accounts"],
            },
        )

    if path == "/accounts" and method == "GET":
        return render_accounts_response(
            start_response,
            platform=platform,
            query=query,
            report_date=query_param(environ, "report_date", ""),
            notice=notice,
            error=error,
        )

    if path == "/credentials" and method == "GET":
        return render_credentials_response(
            start_response,
            platform=platform,
            query=query,
            notice=notice,
            error=error,
        )

    if path == "/report-sheets" and method == "GET":
        settings = REPOSITORY.get_integration_settings()
        body = render_report_sheets_page(
            REPOSITORY.list_monthly_report_sheets(),
            notice=notice,
            error=error,
            settings=settings,
            default_month_key=date.today().strftime("%Y-%m"),
        )
        return respond_html(start_response, body)

    if path == "/sync-runs" and method == "GET":
        body = render_sync_runs_page(
            REPOSITORY.list_sync_runs(),
            notice=notice,
            error=error,
        )
        return respond_html(start_response, body)

    if path == "/accounts/new" and method == "GET":
        return redirect_to(start_response, "/accounts", platform=platform)

    if path == "/credentials/new" and method == "GET":
        return redirect_to(start_response, "/credentials", platform=platform)

    if path == "/report-sheets/new" and method == "GET":
        body = render_report_sheet_form(month_key=date.today().strftime("%Y-%m"))
        return respond_html(start_response, body)

    if path == "/accounts/new" and method == "POST":
        form = parse_form(environ)
        required = ("platform", "account_name", "account_identifier", "timezone_name", "operator_email")
        if not all(form.get(field, "").strip() for field in required):
            return render_accounts_response(
                start_response,
                platform=form.get("platform", platform),
                query=query,
                error="必須項目を入力してください。",
                status="400 Bad Request",
            )

        credential_profile_id = form.get("credential_profile_id", "").strip()
        REPOSITORY.create_account(
            platform=form["platform"],
            account_name=form["account_name"].strip(),
            account_identifier=form["account_identifier"].strip(),
            timezone_name=form["timezone_name"].strip(),
            credential_profile_id=int(credential_profile_id) if credential_profile_id else None,
            operator_email=form["operator_email"].strip(),
            parent_account=form.get("parent_account", "-").strip(),
        )
        return redirect_to(
            start_response,
            "/accounts",
            platform=form["platform"],
            notice="アカウントを追加しました。",
        )

    if path == "/accounts/link" and method == "POST":
        form = parse_form(environ)
        selected_platform = form.get("platform", platform).strip()
        credential_id_raw = form.get("credential_profile_id", "").strip()
        selected_account_ids = [
            identifier.strip()
            for identifier in form.get("selected_account_ids", "").split(",")
            if identifier.strip()
        ]
        if selected_platform not in SUPPORTED_PLATFORMS:
            return render_accounts_response(
                start_response,
                platform=platform,
                query=query,
                error="連携対象のプラットフォームが不正です。",
                status="400 Bad Request",
            )
        credentials = {
            str(row["id"]): row
            for row in REPOSITORY.list_credentials(selected_platform)
        }
        credential = credentials.get(credential_id_raw)
        if credential is None or not selected_account_ids:
            return render_accounts_response(
                start_response,
                platform=selected_platform,
                query=query,
                error="認証プロフィールと広告アカウントを選択してください。",
                status="400 Bad Request",
                modal_state={
                    "open": True,
                    "step": 3 if credential_id_raw else 2,
                    "platform": selected_platform,
                    "credential_profile_id": credential_id_raw,
                    "selected_account_ids": selected_account_ids,
                    "error": "認証プロフィールと広告アカウントを選択してください。",
                },
            )

        try:
            if selected_platform == "meta":
                payload = fetch_linkable_accounts(
                    platform=selected_platform,
                    credential_profile_id=int(credential_id_raw),
                )
                discoverable_lookup = {
                    account["account_identifier"]: account
                    for account in payload["accounts"]
                }
                discoverable_accounts = [
                    discoverable_lookup[identifier]
                    for identifier in selected_account_ids
                    if identifier in discoverable_lookup
                ]
            else:
                discoverable_accounts = find_discoverable_accounts(
                    selected_platform,
                    selected_account_ids,
                )
        except (ConfigError, MetaApiError, ValueError) as exc:
            return render_accounts_response(
                start_response,
                platform=selected_platform,
                query=query,
                error=str(exc),
                status="400 Bad Request",
                modal_state={
                    "open": True,
                    "step": 3,
                    "platform": selected_platform,
                    "credential_profile_id": credential_id_raw,
                    "selected_account_ids": selected_account_ids,
                    "error": str(exc),
                },
            )
        if not discoverable_accounts:
            return render_accounts_response(
                start_response,
                platform=selected_platform,
                query=query,
                error="選択した広告アカウントが見つかりませんでした。",
                status="400 Bad Request",
                modal_state={
                    "open": True,
                    "step": 3,
                    "platform": selected_platform,
                    "credential_profile_id": credential_id_raw,
                    "selected_account_ids": selected_account_ids,
                    "error": "選択した広告アカウントが見つかりませんでした。",
                },
            )

        existing_account_ids = {
            row["account_identifier"]
            for row in REPOSITORY.list_accounts(selected_platform)
        }
        created_count = 0
        skipped_count = 0
        for account in discoverable_accounts:
            if account["account_identifier"] in existing_account_ids:
                skipped_count += 1
                continue
            REPOSITORY.create_account(
                platform=selected_platform,
                account_name=account["account_name"],
                account_identifier=account["account_identifier"],
                timezone_name=account["timezone_name"],
                credential_profile_id=int(credential_id_raw),
                operator_email=credential["creator_email"],
                parent_account=account["parent_account"],
                selection_source="link_modal",
            )
            existing_account_ids.add(account["account_identifier"])
            created_count += 1

        message = f"{created_count}件の広告アカウントを連携しました。"
        if skipped_count:
            message += f" 連携済み {skipped_count}件はスキップしました。"
        return redirect_to(
            start_response,
            "/accounts",
            platform=selected_platform,
            notice=message,
        )

    if path == "/credentials/new" and method == "POST":
        form = parse_form(environ)
        auth_type = form.get("auth_type", "").strip() or "manual"
        if auth_type == "oauth" and form.get("platform", "").strip() not in {"google", "meta"}:
            return render_credentials_response(
                start_response,
                platform=form.get("platform", platform),
                query=query,
                error="このプラットフォームの OAuth 連携はまだ未対応です。",
                status="400 Bad Request",
                modal_state={
                    "open": True,
                    "step": 2,
                    **form,
                    "error": "このプラットフォームの OAuth 連携はまだ未対応です。",
                },
            )
        required = ["platform", "creator_email", "auth_type"]
        if auth_type != "oauth":
            required.extend(["profile_name", "profile_identifier"])
        if not all(form.get(field, "").strip() for field in required):
            return render_credentials_response(
                start_response,
                platform=form.get("platform", platform),
                query=query,
                error="必須項目を入力してください。",
                status="400 Bad Request",
                modal_state={
                    "open": True,
                    "step": 3,
                    **form,
                    "error": "必須項目を入力してください。",
                },
            )

        if auth_type == "oauth" and form["platform"].strip() in {"google", "meta"}:
            try:
                authorization_url = start_credential_oauth_flow(form)
            except Exception as exc:
                return render_credentials_response(
                    start_response,
                    platform=form.get("platform", platform),
                    query=query,
                    error=str(exc),
                    status="400 Bad Request",
                    modal_state={
                        "open": True,
                        "step": 3,
                        **form,
                        "error": str(exc),
                    },
                )
            return redirect(start_response, authorization_url)

        REPOSITORY.create_credential(
            platform=form["platform"],
            profile_name=form["profile_name"].strip(),
            profile_identifier=form["profile_identifier"].strip(),
            creator_email=form["creator_email"].strip(),
            auth_expiry=form.get("auth_expiry", "").strip(),
            auth_type=form.get("auth_type", "manual").strip() or "manual",
            external_user_id=form.get("external_user_id", "").strip(),
            token_expires_at=form.get("token_expires_at", "").strip(),
        )
        return redirect_to(
            start_response,
            "/credentials",
            platform=form["platform"],
            notice="認証情報を追加しました。",
        )

    if path == "/oauth/google/callback" and method == "GET":
        oauth_error = query_param(environ, "error", "")
        state = query_param(environ, "state", "")
        code = query_param(environ, "code", "")
        if oauth_error:
            return redirect_to(
                start_response,
                "/credentials",
                platform="google",
                error=f"Google OAuth がキャンセルされました: {oauth_error}",
            )
        if not state or not code:
            return redirect_to(
                start_response,
                "/credentials",
                platform="google",
                error="Google OAuth のコールバックに必要な情報が不足しています。",
            )
        try:
            profile_name = complete_credential_oauth("google", state=state, code=code)
        except Exception as exc:
            return redirect_to(
                start_response,
                "/credentials",
                platform="google",
                error=str(exc),
            )
        return redirect_to(
            start_response,
            "/credentials",
            platform="google",
            notice=f"{profile_name} の Google 認証情報を追加しました。",
        )

    if path == "/oauth/meta/callback" and method == "GET":
        oauth_error = query_param(environ, "error", "")
        error_reason = query_param(environ, "error_reason", "")
        error_description = query_param(environ, "error_description", "")
        state = query_param(environ, "state", "")
        code = query_param(environ, "code", "")
        if oauth_error or error_reason:
            message = error_description or error_reason or oauth_error
            return redirect_to(
                start_response,
                "/credentials",
                platform="meta",
                error=f"Meta OAuth がキャンセルされました: {message}",
            )
        if not state or not code:
            return redirect_to(
                start_response,
                "/credentials",
                platform="meta",
                error="Meta OAuth のコールバックに必要な情報が不足しています。",
            )
        try:
            profile_name = complete_credential_oauth("meta", state=state, code=code)
        except Exception as exc:
            return redirect_to(
                start_response,
                "/credentials",
                platform="meta",
                error=str(exc),
            )
        return redirect_to(
            start_response,
            "/credentials",
            platform="meta",
            notice=f"{profile_name} の Meta 認証情報を追加しました。",
        )

    if path == "/report-sheets/new" and method == "POST":
        form = parse_form(environ)
        month_key = form.get("month_key", "").strip()
        spreadsheet_url = form.get("spreadsheet_url", "").strip()
        spreadsheet_title = form.get("spreadsheet_title", "").strip()
        status_value = form.get("status", "有効").strip() or "有効"
        notes = form.get("notes", "").strip()

        if (
            not MONTH_KEY_PATTERN.match(month_key)
            or not spreadsheet_url
            or not spreadsheet_title
        ):
            body = render_report_sheet_form(
                month_key=month_key,
                spreadsheet_url=spreadsheet_url,
                spreadsheet_title=spreadsheet_title,
                status=status_value,
                notes=notes,
                error="対象月・スプレッドシートURL・スプレッドシート名を入力してください。",
            )
            return respond_html(start_response, body, "400 Bad Request")

        REPOSITORY.save_monthly_report_sheet(
            month_key=month_key,
            spreadsheet_url=spreadsheet_url,
            spreadsheet_title=spreadsheet_title,
            status=status_value,
            notes=notes,
        )
        return redirect_to(
            start_response,
            "/report-sheets",
            notice=f"{month_key} の出力先スプレッドシートを保存しました。",
        )

    if path == "/report-sheets/auto-create" and method == "POST":
        form = parse_form(environ)
        month_key = form.get("month_key", "").strip()
        if not MONTH_KEY_PATTERN.match(month_key):
            return redirect_to(
                start_response,
                "/report-sheets",
                error="対象月は YYYY-MM 形式で入力してください。",
            )
        try:
            result = ensure_monthly_report_sheet(
                REPOSITORY,
                month_key=month_key,
                settings=REPOSITORY.get_integration_settings(),
                project_root=PROJECT_ROOT,
            )
        except Exception as exc:
            return redirect_to(
                start_response,
                "/report-sheets",
                error=str(exc),
            )
        message = (
            f"{month_key} の月別スプシを共有ドライブへ自動作成しました。"
            if result.created
            else f"{month_key} の月別スプシはすでに登録済みです。"
        )
        return redirect_to(
            start_response,
            "/report-sheets",
            notice=message,
        )

    if path.startswith("/credentials/") and path.endswith("/reauth") and method == "POST":
        credential_id = int(path.split("/")[2])
        REPOSITORY.reauth_credential(credential_id)
        return redirect_to(
            start_response,
            "/credentials",
            platform=platform,
            q=query,
            notice="再認証フラグを更新しました。",
        )

    if path.startswith("/credentials/") and path.endswith("/delete") and method == "POST":
        credential_id = int(path.split("/")[2])
        REPOSITORY.delete_credential(credential_id)
        return redirect_to(
            start_response,
            "/credentials",
            platform=platform,
            q=query,
            notice="認証情報を削除しました。",
        )

    if path.startswith("/accounts/") and path.endswith("/delete") and method == "POST":
        account_id = int(path.split("/")[2])
        REPOSITORY.delete_account(account_id)
        return redirect_to(
            start_response,
            "/accounts",
            platform=platform,
            q=query,
            notice="アカウントを削除しました。",
        )

    if path.startswith("/report-sheets/") and path.endswith("/delete") and method == "POST":
        sheet_id = int(path.split("/")[2])
        REPOSITORY.delete_monthly_report_sheet(sheet_id)
        return redirect_to(
            start_response,
            "/report-sheets",
            notice="月別スプレッドシートを削除しました。",
        )

    if path == "/accounts/meta/sync" and method == "POST":
        form = parse_form(environ)
        try:
            job = run_meta_daily_sync_job(
                repository=REPOSITORY,
                settings=REPOSITORY.get_integration_settings(),
                project_root=PROJECT_ROOT,
                report_date_input=form.get("report_date", "").strip(),
                trigger_source="manual",
            )
        except Exception as exc:
            return redirect_to(
                start_response,
                "/accounts",
                platform="meta",
                report_date=form.get("report_date", "").strip(),
                error=str(exc),
            )

        result = job.result
        failure_message = (
            " / ".join(result.failure_messages[:3])
            + (" ほか" if result.failure_count > 3 else "")
            if result.failure_count
            else ""
        )
        return redirect_to(
            start_response,
            "/accounts",
            platform="meta",
            report_date=result.report_date,
            notice=(
                f"{result.report_date} の Meta 数値を転記しました。"
                f" 対象アカウント {result.account_count}件 / 成功 {result.success_count}件"
                f" / 更新 {result.updated_count}件 / 追加 {result.appended_count}件"
            ),
            error=(
                f"{result.failure_count}件の同期に失敗しました。 {failure_message}"
                if result.failure_count
                else ""
            ),
        )

    if path == "/accounts/meta/monthly-sync" and method == "POST":
        form = parse_form(environ)
        try:
            job = run_meta_monthly_sync_job(
                settings=REPOSITORY.get_integration_settings(),
                repository=REPOSITORY,
                project_root=PROJECT_ROOT,
                report_date_input=form.get("report_date", "").strip(),
                trigger_source="manual",
            )
        except Exception as exc:
            return redirect_to(
                start_response,
                "/accounts",
                platform="meta",
                report_date=form.get("report_date", "").strip(),
                error=str(exc),
            )

        result = job.result
        created_message = (
            f" 月次スプシを新規作成: {result.spreadsheet_title}"
            if result.created_spreadsheet
            else ""
        )
        return redirect_to(
            start_response,
            "/accounts",
            platform="meta",
            report_date=result.report_date,
            notice=(
                f"{result.report_date} の Meta 消化キャンペーンを月次スプシへ転記しました。"
                f" 対象アカウント {result.account_count}件 / 行数 {result.row_count}件 / 更新 {result.updated_count}件 / 追加 {result.appended_count}件。"
                f"{created_message}"
            ),
        )

    if path == "/jobs/meta/monthly-sync" and method in {"GET", "POST"}:
        settings = REPOSITORY.get_integration_settings()
        configured_token = settings.get("job_trigger_token", "").strip()
        supplied_token = (
            environ.get("HTTP_X_FREDCORE_JOB_TOKEN", "").strip()
            or query_param(environ, "token", "")
        )
        cron_secret = os.environ.get("CRON_SECRET", "").strip()
        auth_header = environ.get("HTTP_AUTHORIZATION", "").strip()
        token_allowed = bool(configured_token) and supplied_token == configured_token
        cron_allowed = bool(cron_secret) and auth_header == f"Bearer {cron_secret}"
        if (configured_token or cron_secret) and not (token_allowed or cron_allowed):
            return respond_json(
                start_response,
                {"ok": False, "error": "invalid job token"},
                "403 Forbidden",
            )

        report_date = query_param(environ, "report_date", "")
        try:
            job = run_meta_monthly_sync_job(
                settings=settings,
                repository=REPOSITORY,
                project_root=PROJECT_ROOT,
                report_date_input=report_date,
                trigger_source="cron",
            )
        except Exception as exc:
            return respond_json(
                start_response,
                {"ok": False, "error": str(exc)},
                "500 Internal Server Error",
            )

        result = job.result
        return respond_json(
            start_response,
            {
                "ok": True,
                "sync_run_id": job.sync_run_id,
                "report_date": result.report_date,
                "month_key": result.month_key,
                "account_count": result.account_count,
                "row_count": result.row_count,
                "updated_count": result.updated_count,
                "appended_count": result.appended_count,
                "spreadsheet_url": result.spreadsheet_url,
                "spreadsheet_title": result.spreadsheet_title,
                "created_spreadsheet": result.created_spreadsheet,
            },
        )

    if path == "/jobs/meta/daily-sync" and method in {"GET", "POST"}:
        settings = REPOSITORY.get_integration_settings()
        configured_token = settings.get("job_trigger_token", "").strip()
        supplied_token = (
            environ.get("HTTP_X_FREDCORE_JOB_TOKEN", "").strip()
            or query_param(environ, "token", "")
        )
        cron_secret = os.environ.get("CRON_SECRET", "").strip()
        auth_header = environ.get("HTTP_AUTHORIZATION", "").strip()
        token_allowed = bool(configured_token) and supplied_token == configured_token
        cron_allowed = bool(cron_secret) and auth_header == f"Bearer {cron_secret}"
        if (configured_token or cron_secret) and not (token_allowed or cron_allowed):
            return respond_json(
                start_response,
                {"ok": False, "error": "invalid job token"},
                "403 Forbidden",
            )

        report_date = query_param(environ, "report_date", "")
        try:
            job = run_meta_daily_sync_job(
                repository=REPOSITORY,
                settings=settings,
                project_root=PROJECT_ROOT,
                report_date_input=report_date,
                trigger_source="cron",
            )
        except Exception as exc:
            return respond_json(
                start_response,
                {"ok": False, "error": str(exc)},
                "500 Internal Server Error",
            )

        result = job.result
        return respond_json(
            start_response,
            {
                "ok": result.failure_count == 0,
                "sync_run_id": job.sync_run_id,
                "report_date": result.report_date,
                "account_count": result.account_count,
                "row_count": result.row_count,
                "updated_count": result.updated_count,
                "appended_count": result.appended_count,
                "success_count": result.success_count,
                "failure_count": result.failure_count,
                "failure_messages": list(result.failure_messages),
            },
            "200 OK" if result.failure_count == 0 else "207 Multi-Status",
        )

    if path == "/settings" and method == "GET":
        body = render_settings_page(
            REPOSITORY.get_integration_settings(),
            notice=notice,
            error=error,
        )
        return respond_html(start_response, body)

    if path == "/settings" and method == "POST":
        form = parse_form(environ)
        values = {
            key: form.get(key, "").strip()
            for key in INTEGRATION_DEFAULTS
            if key != "include_zero_spend_rows"
        }
        values["include_zero_spend_rows"] = (
            "true" if form.get("include_zero_spend_rows") else "false"
        )
        REPOSITORY.save_integration_settings(values)
        return redirect_to(start_response, "/settings", notice="設定を保存しました。")

    return respond_html(start_response, b"Not Found", "404 Not Found")


app = application


def main() -> None:
    if os.environ.get("FREDCORE_RUN_MAIN") != "1":
        raise SystemExit(run_with_reloader())
    ensure_repository_ready()
    with make_server("127.0.0.1", 8000, application) as server:
        print("FredCore admin UI: http://127.0.0.1:8000 (auto-reload enabled)")
        server.serve_forever()


if __name__ == "__main__":
    main()
