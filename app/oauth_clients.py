from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional
from urllib.parse import urlencode

import requests

from app.config import ConfigError
from app.meta_sync import merged_integration_settings


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_OAUTH_SCOPES = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/adwords",
)

META_DEFAULT_OAUTH_SCOPES = (
    "ads_read",
    "ads_management",
    "business_management",
)

TIKTOK_AUTH_URL = "https://ads.tiktok.com/marketing_api/auth"
TIKTOK_TOKEN_URL = "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/"
TIKTOK_USERINFO_URL = "https://business-api.tiktok.com/open_api/v1.3/user/info/"


class OAuthError(RuntimeError):
    """Raised when an OAuth flow cannot be completed."""


@dataclass(frozen=True)
class OAuthAppConfig:
    platform: str
    client_id: str
    client_secret: str
    authorization_url: str
    token_url: str
    redirect_uri: str
    scopes: tuple[str, ...]
    graph_api_version: str = "v22.0"


@dataclass(frozen=True)
class OAuthTokenPayload:
    access_token: str
    refresh_token: str
    token_expires_at: str
    raw_payload: Mapping[str, object]


@dataclass(frozen=True)
class OAuthProfile:
    external_user_id: str
    profile_name: str
    profile_identifier: str
    metadata: Mapping[str, object]


def create_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def base64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def oauth_redirect_uri(base_url: str, platform: str) -> str:
    clean_base = base_url.strip().rstrip("/")
    if not clean_base:
        raise ConfigError("アプリのベースURLを設定してください。")
    return f"{clean_base}/oauth/{platform}/callback"


def google_oauth_config(settings: Mapping[str, str]) -> OAuthAppConfig:
    merged = merged_integration_settings(settings)
    client_id = merged.get("google_oauth_client_id", "").strip()
    client_secret = merged.get("google_oauth_client_secret", "").strip()
    if not client_id or not client_secret:
        raise ConfigError("Google OAuth クライアントID / シークレットを設定してください。")
    return OAuthAppConfig(
        platform="google",
        client_id=client_id,
        client_secret=client_secret,
        authorization_url=GOOGLE_AUTH_URL,
        token_url=GOOGLE_TOKEN_URL,
        redirect_uri=oauth_redirect_uri(merged.get("app_base_url", ""), "google"),
        scopes=GOOGLE_OAUTH_SCOPES,
    )


def meta_oauth_config(settings: Mapping[str, str]) -> OAuthAppConfig:
    merged = merged_integration_settings(settings)
    client_id = merged.get("meta_app_id", "").strip()
    client_secret = merged.get("meta_app_secret", "").strip()
    if not client_id or not client_secret:
        raise ConfigError("Meta App ID / App Secret を設定してください。")
    graph_api_version = merged.get("meta_graph_api_version", "").strip() or "v22.0"
    return OAuthAppConfig(
        platform="meta",
        client_id=client_id,
        client_secret=client_secret,
        authorization_url=f"https://www.facebook.com/{graph_api_version}/dialog/oauth",
        token_url=f"https://graph.facebook.com/{graph_api_version}/oauth/access_token",
        redirect_uri=oauth_redirect_uri(merged.get("app_base_url", ""), "meta"),
        scopes=META_DEFAULT_OAUTH_SCOPES,
        graph_api_version=graph_api_version,
    )


def build_google_authorization_url(
    config: OAuthAppConfig,
    *,
    state: str,
    code_verifier: str,
) -> str:
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": " ".join(config.scopes),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
        "code_challenge": base64url_sha256(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{config.authorization_url}?{urlencode(params)}"


def build_meta_authorization_url(
    config: OAuthAppConfig,
    *,
    state: str,
) -> str:
    params = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": ",".join(config.scopes),
        "state": state,
    }
    return f"{config.authorization_url}?{urlencode(params)}"


def exchange_google_code(
    config: OAuthAppConfig,
    *,
    code: str,
    code_verifier: str,
    session: Optional[requests.Session] = None,
) -> OAuthTokenPayload:
    http = session or requests.Session()
    response = http.post(
        config.token_url,
        data={
            "code": code,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    payload = _json_or_error(response, "Google token exchange failed.")
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise OAuthError("Google からアクセストークンを取得できませんでした。")
    return OAuthTokenPayload(
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token") or "").strip(),
        token_expires_at=_expiry_from_seconds(payload.get("expires_in")),
        raw_payload=payload,
    )


def fetch_google_profile(
    token: OAuthTokenPayload,
    *,
    session: Optional[requests.Session] = None,
) -> OAuthProfile:
    http = session or requests.Session()
    response = http.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {token.access_token}"},
        timeout=30,
    )
    payload = _json_or_error(response, "Google profile fetch failed.")
    external_user_id = str(payload.get("sub") or "").strip()
    profile_identifier = str(payload.get("email") or external_user_id).strip()
    profile_name = str(payload.get("name") or profile_identifier or external_user_id).strip()
    if not external_user_id:
        raise OAuthError("Google ユーザー情報の取得に失敗しました。")
    return OAuthProfile(
        external_user_id=external_user_id,
        profile_name=profile_name,
        profile_identifier=profile_identifier,
        metadata=payload,
    )


def refresh_google_access_token(
    config: OAuthAppConfig,
    refresh_token: str,
    *,
    session: Optional[requests.Session] = None,
) -> OAuthTokenPayload:
    http = session or requests.Session()
    response = http.post(
        GOOGLE_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    payload = _json_or_error(response, "Google token refresh failed.")
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise OAuthError("Google トークンの更新に失敗しました。")
    return OAuthTokenPayload(
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=_expiry_from_seconds(payload.get("expires_in")),
        raw_payload=payload,
    )


def exchange_meta_code(
    config: OAuthAppConfig,
    *,
    code: str,
    session: Optional[requests.Session] = None,
) -> OAuthTokenPayload:
    http = session or requests.Session()
    response = http.get(
        config.token_url,
        params={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
            "code": code,
        },
        timeout=30,
    )
    payload = _json_or_error(response, "Meta token exchange failed.")
    short_lived_token = str(payload.get("access_token") or "").strip()
    if not short_lived_token:
        raise OAuthError("Meta からアクセストークンを取得できませんでした。")

    long_lived_payload = payload
    long_lived_token = short_lived_token
    refresh_url = f"https://graph.facebook.com/{config.graph_api_version}/oauth/access_token"
    refresh_response = http.get(
        refresh_url,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "fb_exchange_token": short_lived_token,
        },
        timeout=30,
    )
    if refresh_response.ok:
        refreshed = refresh_response.json()
        if refreshed.get("access_token"):
            long_lived_payload = refreshed
            long_lived_token = str(refreshed.get("access_token") or "").strip()

    return OAuthTokenPayload(
        access_token=long_lived_token,
        refresh_token="",
        token_expires_at=_expiry_from_seconds(long_lived_payload.get("expires_in")),
        raw_payload=long_lived_payload,
    )


def fetch_meta_profile(
    config: OAuthAppConfig,
    token: OAuthTokenPayload,
    *,
    session: Optional[requests.Session] = None,
) -> OAuthProfile:
    http = session or requests.Session()
    response = http.get(
        f"https://graph.facebook.com/{config.graph_api_version}/me",
        params={
            "fields": "id,name",
            "access_token": token.access_token,
        },
        timeout=30,
    )
    payload = _json_or_error(response, "Meta profile fetch failed.")
    external_user_id = str(payload.get("id") or "").strip()
    profile_identifier = str(payload.get("email") or external_user_id).strip()
    profile_name = str(payload.get("name") or profile_identifier or external_user_id).strip()
    if not external_user_id:
        raise OAuthError("Meta ユーザー情報の取得に失敗しました。")
    return OAuthProfile(
        external_user_id=external_user_id,
        profile_name=profile_name,
        profile_identifier=profile_identifier,
        metadata=payload,
    )


def metadata_json_for_oauth(
    *,
    platform: str,
    auth_type: str,
    profile: OAuthProfile,
    token: OAuthTokenPayload,
) -> str:
    return json.dumps(
        {
            "platform": platform,
            "auth_type": auth_type,
            "profile": dict(profile.metadata),
            "token": dict(token.raw_payload),
        },
        ensure_ascii=False,
    )


def tiktok_oauth_config(settings: Mapping[str, str]) -> OAuthAppConfig:
    merged = merged_integration_settings(settings)
    app_id = merged.get("tiktok_app_id", "").strip()
    app_secret = merged.get("tiktok_app_secret", "").strip()
    if not app_id or not app_secret:
        raise ConfigError("TikTok App ID / App Secret を設定してください。")
    return OAuthAppConfig(
        platform="tiktok",
        client_id=app_id,
        client_secret=app_secret,
        authorization_url=TIKTOK_AUTH_URL,
        token_url=TIKTOK_TOKEN_URL,
        redirect_uri=oauth_redirect_uri(merged.get("app_base_url", ""), "tiktok"),
        scopes=(),
    )


def build_tiktok_authorization_url(config: OAuthAppConfig, *, state: str) -> str:
    params = {
        "app_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "state": state,
    }
    return f"{config.authorization_url}?{urlencode(params)}"


def exchange_tiktok_code(
    config: OAuthAppConfig,
    *,
    auth_code: str,
    session: Optional[requests.Session] = None,
) -> OAuthTokenPayload:
    http = session or requests.Session()
    response = http.post(
        config.token_url,
        json={
            "app_id": config.client_id,
            "secret": config.client_secret,
            "auth_code": auth_code,
        },
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise OAuthError("TikTok token exchange failed.") from exc
    code = body.get("code", -1)
    if code != 0:
        message = body.get("message") or str(body)
        raise OAuthError(f"TikTok token exchange error [{code}]: {message}")
    data = body.get("data", {})
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise OAuthError("TikTok からアクセストークンを取得できませんでした。")
    expires_in = data.get("expires_in") or data.get("access_token_expires_in")
    return OAuthTokenPayload(
        access_token=access_token,
        refresh_token="",
        token_expires_at=_expiry_from_seconds(expires_in),
        raw_payload=data,
    )


def fetch_tiktok_profile(
    token: OAuthTokenPayload,
    *,
    session: Optional[requests.Session] = None,
) -> OAuthProfile:
    http = session or requests.Session()
    response = http.get(
        TIKTOK_USERINFO_URL,
        headers={"Access-Token": token.access_token},
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise OAuthError("TikTok profile fetch failed.") from exc
    code = body.get("code", -1)
    if code != 0:
        message = body.get("message") or str(body)
        raise OAuthError(f"TikTok profile fetch error [{code}]: {message}")
    data = body.get("data", {})
    # TikTok Business API returns advertiser_id or open_id depending on app type
    user_id = str(
        data.get("user_id") or data.get("advertiser_id") or data.get("open_id") or ""
    ).strip()
    username = str(
        data.get("display_name") or data.get("username") or data.get("advertiser_name") or user_id
    ).strip()
    email = str(data.get("email") or username).strip()
    if not user_id:
        raise OAuthError(
            f"TikTok ユーザー情報の取得に失敗しました。(レスポンス: {list(data.keys())})"
        )
    return OAuthProfile(
        external_user_id=user_id,
        profile_name=username,
        profile_identifier=email,
        metadata=data,
    )


def _expiry_from_seconds(value) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return ""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return expires_at.replace(microsecond=0).isoformat()


def _json_or_error(response: requests.Response, default_message: str):
    try:
        payload = response.json()
    except ValueError as exc:
        raise OAuthError(default_message) from exc
    if response.status_code >= 400 or "error" in payload:
        error = payload.get("error", {})
        if isinstance(error, dict):
            message = error.get("message") or default_message
        else:
            message = str(error or payload or default_message)
        raise OAuthError(message)
    return payload
