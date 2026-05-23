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
from app.config import ConfigError, get_config
from app.dates import default_target_date
from app.meta_api import MetaApiError, MetaClient
from app.oauth_clients import (
    OAuthError,
    build_google_authorization_url,
    build_meta_authorization_url,
    build_tiktok_authorization_url,
    create_oauth_state,
    exchange_google_code,
    exchange_meta_code,
    exchange_tiktok_code,
    fetch_google_profile,
    fetch_meta_profile,
    fetch_tiktok_profile,
    google_oauth_config,
    meta_oauth_config,
    metadata_json_for_oauth,
    tiktok_oauth_config,
)
from app.sync_jobs import run_google_ads_monthly_sync_job, run_meta_monthly_sync_job, run_tiktok_monthly_sync_job
from app.auth import (
    clear_session_cookie,
    generate_session_token,
    get_session_cookie,
    hash_password,
    make_session_cookie,
    session_expires_at,
    verify_password,
)
from app.admin_views import (
    render_accounts_page,
    render_credentials_page,
    render_login_page,
    render_new_user_page,
    render_report_sheets_page,
    render_setup_page,
    render_sync_runs_page,
    render_users_page,
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
    _REPOSITORY_READY = True


_PUBLIC_PATHS = frozenset({"/login", "/setup"})
_PUBLIC_PREFIXES = ("/static/", "/oauth/", "/jobs/")


def get_current_user(environ) -> Optional[Dict]:
    token = get_session_cookie(environ)
    if not token:
        return None
    row = REPOSITORY.get_user_session(token)
    if row is None:
        return None
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if str(row["expires_at"]) < now:
        REPOSITORY.delete_user_session(token)
        return None
    if str(row.get("status", "有効")) != "有効":
        return None
    return {
        "id": row["user_id"],
        "email": str(row["email"]),
        "name": str(row["name"]),
        "role": str(row["role"]),
    }


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
    current_user: Optional[Dict] = None,
):
    integration_settings = get_config()
    sync_date = report_date or default_target_date(
        integration_settings.get("report_timezone", "Asia/Tokyo")
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
        current_user=current_user,
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
    current_user: Optional[Dict] = None,
):
    body = render_credentials_page(
        REPOSITORY.list_credentials(platform, query),
        REPOSITORY.get_platform_counts("credential_profiles"),
        platform,
        query,
        notice=notice,
        error=error,
        credential_modal_state=modal_state,
        current_user=current_user,
    )
    return respond_html(start_response, body, status)


def start_credential_oauth_flow(form: dict):
    settings = get_config()
    platform = form["platform"].strip()
    auth_type = form.get("auth_type", "oauth").strip() or "oauth"
    payload = {
        "platform": platform,
        "auth_type": auth_type,
        "profile_name": form.get("profile_name", "").strip(),
        "profile_identifier": form.get("profile_identifier", "").strip(),
        "creator_email": form.get("creator_email", "").strip(),
        "auth_expiry": form.get("auth_expiry", "").strip(),
        "external_user_id": form.get("external_user_id", "").strip(),
        "token_expires_at": form.get("token_expires_at", "").strip(),
        "reauth_credential_id": form.get("reauth_credential_id", "").strip(),
        "next_reauth_ids": form.get("next_reauth_ids", "").strip(),
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

    if platform == "tiktok":
        config = tiktok_oauth_config(settings)
        REPOSITORY.create_oauth_state(
            state=state,
            platform=platform,
            auth_type=auth_type,
            payload_json=json.dumps(payload, ensure_ascii=False),
            code_verifier="",
            expires_at=expires_at,
        )
        return build_tiktok_authorization_url(config, state=state)

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

    settings = get_config()
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
    elif platform == "tiktok":
        config = tiktok_oauth_config(settings)
        token = exchange_tiktok_code(config, auth_code=code)
        profile = fetch_tiktok_profile(token)
    else:
        raise OAuthError("未対応の OAuth プラットフォームです。")

    profile_name = str(payload.get("profile_name") or profile.profile_name).strip()
    profile_identifier = str(payload.get("profile_identifier") or profile.profile_identifier).strip()
    creator_email = (
        str(payload.get("creator_email") or "").strip()
        or profile.profile_identifier
    )
    auth_expiry = token.token_expires_at or str(payload.get("auth_expiry") or "").strip()
    meta_json = metadata_json_for_oauth(
        platform=platform,
        auth_type=str(state_row["auth_type"] or "oauth"),
        profile=profile,
        token=token,
    )

    reauth_credential_id = str(payload.get("reauth_credential_id") or "").strip()
    if reauth_credential_id:
        REPOSITORY.update_credential_token(
            int(reauth_credential_id),
            profile_name=profile_name,
            profile_identifier=profile_identifier,
            access_token=token.access_token,
            refresh_token=token.refresh_token or "",
            token_expires_at=token.token_expires_at or "",
            auth_expiry=auth_expiry,
            metadata_json=meta_json,
        )
    else:
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
            metadata_json=meta_json,
        )

    next_reauth_ids = str(payload.get("next_reauth_ids") or "").strip()
    if next_reauth_ids:
        ids = [x for x in next_reauth_ids.split(",") if x.strip()]
        if ids:
            next_id = ids[0].strip()
            remaining = ",".join(ids[1:])
            next_credential = REPOSITORY.get_credential(int(next_id))
            if next_credential:
                next_url = start_credential_oauth_flow({
                    "platform": str(next_credential["platform"]),
                    "auth_type": str(next_credential["auth_type"] or "oauth"),
                    "reauth_credential_id": next_id,
                    "next_reauth_ids": remaining,
                })
                return next_url  # signal to caller to redirect to next OAuth

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

    settings = get_config()
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

    # ── /setup: 初回セットアップ（ユーザーが0人のときだけ表示）──────────
    if path == "/setup":
        if REPOSITORY.count_users() > 0:
            return redirect(start_response, "/login")
        if method == "POST":
            form = parse_form(environ)
            name = form.get("name", "").strip()
            email = form.get("email", "").strip()
            password = form.get("password", "").strip()
            if not name or not email or not password:
                return respond_html(start_response, render_setup_page(error="すべての項目を入力してください。"))
            if len(password) < 8:
                return respond_html(start_response, render_setup_page(error="パスワードは8文字以上で入力してください。"))
            try:
                REPOSITORY.create_user(
                    email=email,
                    name=name,
                    password_hash=hash_password(password),
                    role="admin",
                )
            except Exception as exc:
                return respond_html(start_response, render_setup_page(error=str(exc)))
            return redirect(start_response, "/login")
        return respond_html(start_response, render_setup_page())

    # ── /login ─────────────────────────────────────────────────────────────
    if path == "/login":
        if REPOSITORY.count_users() == 0:
            return redirect(start_response, "/setup")
        if method == "POST":
            form = parse_form(environ)
            email = form.get("email", "").strip()
            password = form.get("password", "").strip()
            user = REPOSITORY.get_user_by_email(email)
            if user and verify_password(str(user["password_hash"]), password):
                token = generate_session_token()
                expires = session_expires_at()
                REPOSITORY.create_user_session(token, int(user["id"]), expires)
                next_url = form.get("next", "").strip() or "/accounts"
                body = b""
                start_response("302 Found", [
                    ("Location", next_url),
                    ("Set-Cookie", make_session_cookie(token)),
                    ("Content-Length", "0"),
                ])
                return [body]
            return respond_html(
                start_response,
                render_login_page(error="メールアドレスまたはパスワードが正しくありません。"),
                "401 Unauthorized",
            )
        return respond_html(start_response, render_login_page())

    # ── /logout ────────────────────────────────────────────────────────────
    if path == "/logout" and method == "POST":
        token = get_session_cookie(environ)
        if token:
            REPOSITORY.delete_user_session(token)
        start_response("302 Found", [
            ("Location", "/login"),
            ("Set-Cookie", clear_session_cookie()),
            ("Content-Length", "0"),
        ])
        return [b""]

    # ── 認証チェック ────────────────────────────────────────────────────────
    is_public = path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES)
    current_user = None
    if not is_public:
        if REPOSITORY.count_users() == 0:
            return redirect(start_response, "/setup")
        current_user = get_current_user(environ)
        if current_user is None:
            return redirect(start_response, f"/login?next={path}")

    if path == "/":
        return redirect(start_response, f"/accounts?platform={platform}")

    if path == "/api/health" and method == "GET":
        return respond_json(
            start_response,
            {
                "ok": True,
                "database_backend": REPOSITORY.backend,
                "app_base_url": (
                    get_config().get("app_base_url", "").strip()
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
            current_user=current_user,
        )

    if path == "/credentials" and method == "GET":
        return render_credentials_response(
            start_response,
            platform=platform,
            query=query,
            notice=notice,
            error=error,
            current_user=current_user,
        )

    if path == "/report-sheets" and method == "GET":
        body = render_report_sheets_page(
            REPOSITORY.list_monthly_report_sheets(),
            notice=notice,
            error=error,
            current_user=current_user,
        )
        return respond_html(start_response, body)

    if path == "/sync-runs" and method == "GET":
        body = render_sync_runs_page(
            REPOSITORY.list_sync_runs(),
            notice=notice,
            error=error,
            current_user=current_user,
        )
        return respond_html(start_response, body)

    if path == "/accounts/new" and method == "GET":
        return redirect_to(start_response, "/accounts", platform=platform)

    if path == "/credentials/new" and method == "GET":
        return redirect_to(start_response, "/credentials", platform=platform)

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
        if auth_type == "oauth" and form.get("platform", "").strip() not in {"google", "meta", "tiktok"}:
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
        required = ["platform", "auth_type"]
        if auth_type != "oauth":
            required.extend(["profile_name", "profile_identifier", "creator_email"])
        if auth_type == "system_user":
            required.append("access_token")
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

        if auth_type == "oauth" and form["platform"].strip() in {"google", "meta", "tiktok"}:
            try:
                authorization_url = start_credential_oauth_flow(form)
            except Exception as exc:
                return redirect_to(
                    start_response,
                    "/credentials",
                    platform=form.get("platform", platform),
                    error=str(exc),
                )
            return redirect(start_response, authorization_url)

        if auth_type == "system_user":
            from app.meta_api import MetaApiError, MetaClient
            _settings = get_config()
            token = form["access_token"].strip()
            try:
                MetaClient(
                    access_token=token,
                    graph_api_version=_settings.get("meta_graph_api_version", "v22.0") or "v22.0",
                ).validate_token()
            except MetaApiError as exc:
                return render_credentials_response(
                    start_response,
                    platform=form.get("platform", platform),
                    query=query,
                    error=f"トークンが無効です: {exc}",
                    status="400 Bad Request",
                    modal_state={
                        "open": True,
                        "step": 3,
                        **form,
                        "error": f"トークンが無効です: {exc}",
                    },
                )

        REPOSITORY.create_credential(
            platform=form["platform"],
            profile_name=form["profile_name"].strip(),
            profile_identifier=form["profile_identifier"].strip(),
            creator_email=form["creator_email"].strip(),
            auth_expiry=form.get("auth_expiry", "").strip(),
            auth_type=form.get("auth_type", "manual").strip() or "manual",
            external_user_id=form.get("external_user_id", "").strip(),
            access_token=form.get("access_token", "").strip(),
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
                error="Google OAuth がキャンセルされました。",
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
                error="Meta OAuth がキャンセルされました。",
            )
        if not state or not code:
            return redirect_to(
                start_response,
                "/credentials",
                platform="meta",
                error="Meta OAuth のコールバックに必要な情報が不足しています。",
            )
        try:
            result = complete_credential_oauth("meta", state=state, code=code)
        except Exception as exc:
            return redirect_to(
                start_response,
                "/credentials",
                platform="meta",
                error=str(exc),
            )
        if result.startswith("https://"):
            return redirect(start_response, result)
        return redirect_to(
            start_response,
            "/credentials",
            platform="meta",
            notice=f"{result} の Meta 認証情報を更新しました。",
        )

    if path == "/oauth/tiktok/callback" and method == "GET":
        oauth_error = query_param(environ, "error", "")
        state = query_param(environ, "state", "")
        auth_code = query_param(environ, "auth_code", "")
        if oauth_error or not auth_code:
            return redirect_to(
                start_response,
                "/credentials",
                platform="tiktok",
                error="TikTok OAuth がキャンセルされました。",
            )
        if not state:
            return redirect_to(
                start_response,
                "/credentials",
                platform="tiktok",
                error="TikTok OAuth のコールバックに必要な情報が不足しています。",
            )
        try:
            profile_name = complete_credential_oauth("tiktok", state=state, code=auth_code)
        except Exception as exc:
            return redirect_to(
                start_response,
                "/credentials",
                platform="tiktok",
                error=str(exc),
            )
        return redirect_to(
            start_response,
            "/credentials",
            platform="tiktok",
            notice=f"{profile_name} の TikTok 認証情報を追加しました。",
        )

    if path == "/credentials/reauth-all" and method == "POST":
        oauth_credentials = [
            r for r in REPOSITORY.list_credentials("meta")
            if str(r["auth_type"] or "") == "oauth"
        ]
        if not oauth_credentials:
            return redirect_to(
                start_response, "/credentials", platform="meta",
                error="再認証対象の Meta OAuth 認証情報がありません。",
            )
        ids = [str(r["id"]) for r in oauth_credentials]
        try:
            authorization_url = start_credential_oauth_flow({
                "platform": "meta",
                "auth_type": "oauth",
                "reauth_credential_id": ids[0],
                "next_reauth_ids": ",".join(ids[1:]),
            })
        except Exception as exc:
            return redirect_to(
                start_response, "/credentials", platform="meta", error=str(exc),
            )
        return redirect(start_response, authorization_url)

    if path.startswith("/credentials/") and path.endswith("/reauth") and method == "POST":
        credential_id = int(path.split("/")[2])
        credential = REPOSITORY.get_credential(credential_id)
        if credential is None or str(credential["auth_type"] or "") != "oauth":
            return redirect_to(
                start_response, "/credentials", platform=platform, q=query,
                error="この認証情報は OAuth 再認証に対応していません。",
            )
        try:
            authorization_url = start_credential_oauth_flow({
                "platform": str(credential["platform"]),
                "auth_type": "oauth",
                "reauth_credential_id": str(credential_id),
                "next_reauth_ids": "",
            })
        except Exception as exc:
            return redirect_to(
                start_response, "/credentials", platform=platform, q=query, error=str(exc),
            )
        return redirect(start_response, authorization_url)

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

    if path == "/accounts/delete-bulk" and method == "POST":
        form = parse_form(environ)
        ids = [int(x) for x in form.get("account_ids", "").split(",") if x.strip().isdigit()]
        for aid in ids:
            REPOSITORY.delete_account(aid)
        return redirect_to(
            start_response,
            "/accounts",
            platform=form.get("platform", platform),
            q=form.get("q", query),
            notice=f"{len(ids)} 件のアカウントの連携を解除しました。",
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
            job = run_meta_monthly_sync_job(
                settings=get_config(),
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
                f"{result.report_date} の Meta 数値をキャンペーン一覧へ反映しました。"
                f" 対象アカウント {result.account_count}件 / 行数 {result.row_count}件 / 更新 {result.updated_count}件 / 追加 {result.appended_count}件。"
                f"{created_message}"
            ),
        )

    if path == "/accounts/google/sync" and method == "POST":
        form = parse_form(environ)
        try:
            job = run_google_ads_monthly_sync_job(
                settings=get_config(),
                repository=REPOSITORY,
                project_root=PROJECT_ROOT,
                report_date_input=form.get("report_date", "").strip(),
                trigger_source="manual",
            )
        except Exception as exc:
            return redirect_to(
                start_response,
                "/accounts",
                platform="google",
                report_date=form.get("report_date", "").strip(),
                error=str(exc),
            )
        result = job.result
        return redirect_to(
            start_response,
            "/accounts",
            platform="google",
            report_date=result.report_date,
            notice=(
                f"{result.report_date} の Google 広告 数値をキャンペーン一覧へ反映しました。"
                f" 対象アカウント {result.account_count}件 / 行数 {result.row_count}件 / 更新 {result.updated_count}件 / 追加 {result.appended_count}件。"
            ),
        )

    if path == "/accounts/tiktok/sync" and method == "POST":
        form = parse_form(environ)
        try:
            job = run_tiktok_monthly_sync_job(
                settings=get_config(),
                repository=REPOSITORY,
                project_root=PROJECT_ROOT,
                report_date_input=form.get("report_date", "").strip(),
                trigger_source="manual",
            )
        except Exception as exc:
            return redirect_to(
                start_response,
                "/accounts",
                platform="tiktok",
                report_date=form.get("report_date", "").strip(),
                error=str(exc),
            )
        result = job.result
        return redirect_to(
            start_response,
            "/accounts",
            platform="tiktok",
            report_date=result.report_date,
            notice=(
                f"{result.report_date} の TikTok 広告 数値をキャンペーン一覧へ反映しました。"
                f" 対象アカウント {result.account_count}件 / 行数 {result.row_count}件 / 更新 {result.updated_count}件 / 追加 {result.appended_count}件。"
            ),
        )

    if path == "/accounts/meta/monthly-sync" and method == "POST":
        form = parse_form(environ)
        try:
            job = run_meta_monthly_sync_job(
                settings=get_config(),
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
        settings = get_config()
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

    if path == "/jobs/daily-sync" and method in {"GET", "POST"}:
        settings = get_config()
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
        results = {}
        for platform, run_job in [
            ("meta", lambda: run_meta_monthly_sync_job(
                settings=settings, repository=REPOSITORY, project_root=PROJECT_ROOT,
                report_date_input=report_date, trigger_source="cron",
            )),
            ("google", lambda: run_google_ads_monthly_sync_job(
                settings=settings, repository=REPOSITORY, project_root=PROJECT_ROOT,
                report_date_input=report_date, trigger_source="cron",
            )),
            ("tiktok", lambda: run_tiktok_monthly_sync_job(
                settings=settings, repository=REPOSITORY, project_root=PROJECT_ROOT,
                report_date_input=report_date, trigger_source="cron",
            )),
        ]:
            try:
                job = run_job()
                r = job.result
                results[platform] = {
                    "ok": True,
                    "sync_run_id": job.sync_run_id,
                    "report_date": r.report_date,
                    "row_count": r.row_count,
                }
            except Exception as exc:
                results[platform] = {"ok": False, "error": str(exc)}

        return respond_json(start_response, {"ok": True, "results": results}, "200 OK")

    if path == "/jobs/meta/daily-sync" and method in {"GET", "POST"}:
        settings = get_config()
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
            "200 OK",
        )

    if path == "/jobs/google/daily-sync" and method in {"GET", "POST"}:
        settings = get_config()
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
            job = run_google_ads_monthly_sync_job(
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
            "200 OK",
        )

    if path == "/jobs/tiktok/daily-sync" and method in {"GET", "POST"}:
        settings = get_config()
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
            job = run_tiktok_monthly_sync_job(
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
            "200 OK",
        )

    if path == "/api/accounts/discover" and method == "GET":
        platform = query_param(environ, "platform", "")
        credential_id_raw = query_param(environ, "credential_id", "")
        def json_response(data, status="200 OK"):
            body = json.dumps(data, ensure_ascii=False).encode()
            start_response(status, [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ])
            return [body]
        if not platform or not credential_id_raw:
            return json_response({"error": "platform と credential_id が必要です"}, "400 Bad Request")
        try:
            credential = REPOSITORY.get_credential(int(credential_id_raw))
        except (ValueError, Exception):
            return json_response({"error": "認証情報が見つかりません"}, "404 Not Found")
        if not credential or credential["platform"] != platform:
            return json_response({"error": "認証情報が見つかりません"}, "404 Not Found")
        linked_ids = {row["account_identifier"] for row in REPOSITORY.list_accounts(platform)}
        if platform == "google":
            from app.campaign_sync import MonthlyCampaignSyncConfig, _get_google_access_token
            from app.google_ads_api import GoogleAdsClient, GoogleAdsError
            try:
                cfg = MonthlyCampaignSyncConfig.from_mapping(get_config(), project_root=PROJECT_ROOT)
                access_token = _get_google_access_token(credential, cfg)
                client = GoogleAdsClient(
                    access_token=access_token,
                    developer_token=cfg.google_ads_developer_token,
                )
                accounts = client.list_accessible_customers()
                return json_response({
                    "accounts": [
                        {**a, "is_linked": a["account_id"] in linked_ids}
                        for a in accounts
                    ]
                })
            except Exception as exc:
                return json_response({"error": str(exc)}, "500 Internal Server Error")
        if platform == "meta":
            from app.meta_api import MetaClient
            _settings = get_config()
            token = str(credential.get("access_token") or _settings.get("meta_access_token") or "").strip()
            if not token:
                return json_response({"error": "Meta アクセストークンがありません"}, "400 Bad Request")
            try:
                graph_api_version = _settings.get("meta_graph_api_version", "v22.0") or "v22.0"
                raw_accounts = MetaClient(access_token=token, graph_api_version=graph_api_version).fetch_accessible_ad_accounts()
                return json_response({
                    "accounts": [
                        {
                            "account_id": a["account_identifier"],
                            "account_name": a["account_name"],
                            "is_linked": a["account_identifier"] in linked_ids,
                        }
                        for a in raw_accounts
                    ]
                })
            except Exception as exc:
                return json_response({"error": str(exc)}, "500 Internal Server Error")
        return json_response({"error": "このプラットフォームは未対応です"}, "400 Bad Request")

    # ── ユーザー管理（管理者のみ）────────────────────────────────────────
    if path == "/users" and method == "GET":
        if current_user.get("role") != "admin":
            return redirect_to(start_response, "/accounts")
        body = render_users_page(
            REPOSITORY.list_users(),
            current_user,
            notice=notice,
            error=error,
        )
        return respond_html(start_response, body)

    if path == "/users/new" and method == "GET":
        if current_user.get("role") != "admin":
            return redirect_to(start_response, "/accounts")
        return respond_html(start_response, render_new_user_page(current_user))

    if path == "/users/new" and method == "POST":
        if current_user.get("role") != "admin":
            return redirect_to(start_response, "/accounts")
        form = parse_form(environ)
        name = form.get("name", "").strip()
        email = form.get("email", "").strip()
        password = form.get("password", "").strip()
        role = form.get("role", "member").strip()
        if not name or not email or not password:
            return respond_html(
                start_response,
                render_new_user_page(current_user, error="すべての項目を入力してください。"),
                "400 Bad Request",
            )
        if len(password) < 8:
            return respond_html(
                start_response,
                render_new_user_page(current_user, error="パスワードは8文字以上で入力してください。"),
                "400 Bad Request",
            )
        try:
            REPOSITORY.create_user(
                email=email,
                name=name,
                password_hash=hash_password(password),
                role=role if role in ("admin", "member") else "member",
            )
        except Exception as exc:
            return respond_html(
                start_response,
                render_new_user_page(current_user, error=str(exc)),
                "400 Bad Request",
            )
        return redirect_to(start_response, "/users", notice=f"{name} を追加しました。")

    if re.match(r"^/users/\d+/delete$", path) and method == "POST":
        if current_user.get("role") != "admin":
            return redirect_to(start_response, "/accounts")
        user_id = int(path.split("/")[2])
        target = REPOSITORY.get_user_by_id(user_id)
        if target and target["email"] == current_user.get("email"):
            return redirect_to(start_response, "/users", error="自分自身は削除できません。")
        if target:
            REPOSITORY.delete_user(user_id)
        return redirect_to(start_response, "/users", notice="ユーザーを削除しました。")

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
