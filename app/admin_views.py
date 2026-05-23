from __future__ import annotations

from html import escape
from typing import Dict, Iterable, Optional
from urllib.parse import urlencode

from app.admin_db import DEFAULT_PLATFORM, SUPPORTED_PLATFORMS
from app.account_linking import ACCOUNT_LINK_FLOW
from app.meta_sync import merged_integration_settings


def _fmt_date(value: str) -> str:
    """ISO 日付 → YYYY/MM/DD"""
    if not value:
        return "ー"
    try:
        s = value.replace("T", " ").split("+")[0].split(".")[0].strip()
        parts = s.split(" ")[0].split("-")
        if len(parts) == 3:
            return f"{parts[0]}/{parts[1]}/{parts[2]}"
    except Exception:
        pass
    return value


def _fmt_datetime(value: str) -> str:
    """ISO 日時 → YYYY/MM/DD HH:MM（秒なし）"""
    if not value:
        return "ー"
    try:
        s = value.replace("T", " ").split("+")[0].split(".")[0].strip()
        parts = s.split(" ")
        date_parts = parts[0].split("-")
        date_str = f"{date_parts[0]}/{date_parts[1]}/{date_parts[2]}" if len(date_parts) == 3 else parts[0]
        if len(parts) > 1:
            t = parts[1].split(":")
            return f"{date_str} {t[0]}:{t[1]}" if len(t) >= 2 else date_str
        return date_str
    except Exception:
        pass
    return value


PLATFORM_LABELS = {
    "meta": "Meta",
    "google": "Google",
    "tiktok": "TikTok",
}

PLATFORM_ICONS = {
    "meta": "∞",
    "google": "G",
    "tiktok": "♪",
}

AUTH_TYPE_LABELS = {
    "manual": "手動登録",
    "oauth": "OAuth連携",
    "service_account": "サービスアカウント",
    "system_user": "System User",
}

CREDENTIAL_AUTH_FLOW = {
    "google": {
        "recommended_auth_type": "oauth",
        "auth_methods": (
            {
                "value": "oauth",
                "label": "Google OAuth",
                "description": "Google 広告のログインアカウントを連携する想定です。",
                "notes": (
                    "将来の OAuth 実装でそのまま使う想定の保存方式です。",
                    "まずは認証プロフィール名と識別子を先に管理できます。",
                ),
            },
            {
                "value": "service_account",
                "label": "サービスアカウント",
                "description": "Google Sheets やバックエンド連携向けの認証情報です。",
                "notes": (
                    "サービスアカウントのメールや用途をプロフィールとして残せます。",
                    "広告アカウント連携よりもシート連携用の管理に向いています。",
                ),
            },
        ),
    },
    "meta": {
        "recommended_auth_type": "oauth",
        "auth_methods": (
            {
                "value": "oauth",
                "label": "Meta OAuth",
                "description": "Facebook ログイン経由で広告アカウントに接続します。",
                "notes": (
                    "ビジネスマネージャー運用の担当者単位で管理できます。",
                ),
            },
        ),
    },
    "tiktok": {
        "recommended_auth_type": "oauth",
        "auth_methods": (
            {
                "value": "oauth",
                "label": "TikTok OAuth",
                "description": "TikTok Ads Manager アカウント連携を想定します。",
                "notes": (
                    "TikTok 側の認証実装を入れた時にそのまま接続しやすい構成です。",
                ),
            },
        ),
    },
}

NAV_ITEMS = [
    ("アカウント連携", "/accounts", "rocket"),
    ("認証情報一覧", "/credentials", "key"),
    ("月別スプシ", "/report-sheets", "table"),
    ("同期履歴", "/sync-runs", "clock"),
    ("ユーザー管理", "/users", "gear"),
]

NAV_ICON_CLASSES = {
    "zap": "bi bi-lightning-charge",
    "rocket": "bi bi-link-45deg",
    "key": "bi bi-key",
    "table": "bi bi-table",
    "clock": "bi bi-clock-history",
    "gear": "bi bi-gear",
}

RULE_OPERATOR_OPTIONS = (
    (">=", "以上"),
    (">", "より大きい"),
    ("<=", "以下"),
    ("<", "より小さい"),
    ("=", "等しい"),
)

RULE_ACTION_OPTIONS = (
    ("通知", "通知"),
    ("入札調整", "入札調整"),
    ("配信停止", "配信停止"),
    ("スプレッドシート記録", "スプレッドシート記録"),
)

RULE_STATUS_OPTIONS = (
    ("有効", "有効"),
    ("停止中", "停止中"),
    ("下書き", "下書き"),
)


def render_layout(title: str, body: str, current_path: str, current_user: Optional[dict] = None) -> bytes:
    nav_html = []
    is_admin = (current_user or {}).get("role") == "admin"
    for label, href, icon in NAV_ITEMS:
        if href == "/users" and not is_admin:
            continue
        active = "active" if current_path.startswith(href) else ""
        nav_html.append(
            f'<a class="nav-item {active}" href="{href}">'
            f'<span class="nav-icon"><i class="{NAV_ICON_CLASSES[icon]}" aria-hidden="true"></i></span>'
            f"<span>{escape(label)}</span>"
            "</a>"
        )

    user_name = (current_user or {}).get("name", "")
    user_email = (current_user or {}).get("email", "")
    user_initial = (user_name or user_email or "?")[0].upper()
    user_html = f"""
      <div class="sidebar-user">
        <div class="avatar">{escape(user_initial)}</div>
        <div style="flex:1;min-width:0">
          <div class="user-name">{escape(user_name or user_email)}</div>
          <div class="user-sub">{escape(user_email)}</div>
        </div>
        <form method="post" action="/logout" style="flex-shrink:0">
          <button class="logout-btn" type="submit" title="ログアウト">
            <i class="bi bi-box-arrow-right" aria-hidden="true"></i>
          </button>
        </form>
      </div>
    """ if current_user else ""

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FredCore | {escape(title)}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.13.1/font/bootstrap-icons.min.css">
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <a class="brand" href="/accounts" aria-label="FredCore">
        <img class="brand-logo" src="/static/fredcore-logo.png" alt="FredCore">
      </a>
      <nav class="sidebar-nav">
        {''.join(nav_html)}
      </nav>
      {user_html}
    </aside>
    <main class="content">
      {body}
    </main>
  </div>
</body>
</html>"""
    return html.encode("utf-8")


def render_auth_page(title: str, body: str) -> bytes:
    """ログイン・セットアップ用のシンプルなレイアウト（サイドバーなし）"""
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FredCore | {escape(title)}</title>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  <div class="auth-shell">
    <div class="auth-card">
      <div class="auth-brand">FredCore</div>
      {body}
    </div>
  </div>
</body>
</html>"""
    return html.encode("utf-8")


def render_login_page(*, error: str = "", next_url: str = "") -> bytes:
    next_input = f'<input type="hidden" name="next" value="{escape(next_url)}">' if next_url else ""
    error_html = f'<div class="feedback feedback-error">{escape(error)}</div>' if error else ""
    body = f"""
    <h1 class="auth-title">ログイン</h1>
    {error_html}
    <form method="post" action="/login" class="auth-form">
      {next_input}
      <label>メールアドレス
        <input type="email" name="email" autocomplete="email" required autofocus>
      </label>
      <label>パスワード
        <input type="password" name="password" autocomplete="current-password" required>
      </label>
      <button class="primary-btn" type="submit">ログイン</button>
    </form>
    """
    return render_auth_page("ログイン", body)


def render_setup_page(*, error: str = "") -> bytes:
    error_html = f'<div class="feedback feedback-error">{escape(error)}</div>' if error else ""
    body = f"""
    <h1 class="auth-title">初回セットアップ</h1>
    <p class="auth-desc">最初の管理者アカウントを作成します。</p>
    {error_html}
    <form method="post" action="/setup" class="auth-form">
      <label>名前
        <input type="text" name="name" required autofocus>
      </label>
      <label>メールアドレス
        <input type="email" name="email" required>
      </label>
      <label>パスワード（8文字以上）
        <input type="password" name="password" minlength="8" required>
      </label>
      <button class="primary-btn" type="submit">管理者アカウントを作成</button>
    </form>
    """
    return render_auth_page("初回セットアップ", body)


def render_users_page(rows, current_user: dict, *, notice: str = "", error: str = "") -> bytes:
    header = """
    <section class="page-head">
      <div>
        <h1>ユーザー管理</h1>
        <p>このアプリにアクセスできるユーザーを管理します。管理者のみ操作できます。</p>
      </div>
      <a class="primary-btn" href="/users/new">新しいユーザーを追加</a>
    </section>
    """
    table_rows = []
    for row in rows:
        role_label = "管理者" if row["role"] == "admin" else "メンバー"
        role_class = "green" if row["role"] == "admin" else "gray"
        is_self = row["email"] == current_user.get("email")
        delete_btn = (
            '<span style="color:#9ca3af;font-size:13px">（自分）</span>'
            if is_self
            else f"""
            <form method="post" action="/users/{row["id"]}/delete">
              <button class="danger-link" type="submit">削除</button>
            </form>
            """
        )
        table_rows.append(f"""
        <tr>
          <td>{escape(row["name"])}</td>
          <td>{escape(row["email"])}</td>
          <td><span class="badge {role_class}">{role_label}</span></td>
          <td>{escape(row["created_at"][:10] if row["created_at"] else "")}</td>
          <td class="action-cell">{delete_btn}</td>
        </tr>
        """)
    body = f"""
    {header}
    {render_feedback(notice, error)}
    <section class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>名前</th>
              <th>メールアドレス</th>
              <th>役割</th>
              <th>作成日</th>
              <th>アクション</th>
            </tr>
          </thead>
          <tbody>{''.join(table_rows)}</tbody>
        </table>
      </div>
    </section>
    """
    return render_layout("ユーザー管理", body, "/users", current_user)


def render_new_user_page(current_user: dict, *, error: str = "") -> bytes:
    error_html = f'<div class="feedback feedback-error">{escape(error)}</div>' if error else ""
    body = f"""
    <section class="page-head">
      <div>
        <h1>ユーザーを追加</h1>
      </div>
    </section>
    {error_html}
    <section class="card" style="max-width:480px">
      <form method="post" action="/users/new" class="stack-form">
        <label>名前
          <input type="text" name="name" required autofocus>
        </label>
        <label>メールアドレス
          <input type="email" name="email" required>
        </label>
        <label>パスワード（8文字以上）
          <input type="password" name="password" minlength="8" required>
        </label>
        <label>役割
          <select name="role">
            <option value="member">メンバー</option>
            <option value="admin">管理者</option>
          </select>
        </label>
        <div style="display:flex;gap:12px;margin-top:8px">
          <button class="primary-btn" type="submit">作成</button>
          <a class="secondary-btn" href="/users">キャンセル</a>
        </div>
      </form>
    </section>
    """
    return render_layout("ユーザーを追加", body, "/users", current_user)


def render_feedback(notice: str = "", error: str = "") -> str:
    if error:
        return f'<div class="feedback feedback-error">{escape(error)}</div>'
    if notice:
        return f'<div class="feedback feedback-notice">{escape(notice)}</div>'
    return ""


def render_tabs(base_path: str, active_platform: str, counts: Dict[str, int], query: str) -> str:
    items = []
    for platform in SUPPORTED_PLATFORMS:
        params = {"platform": platform}
        if query:
            params["q"] = query
        href = f"{base_path}?{urlencode(params)}"
        active = "tab active" if platform == active_platform else "tab"
        items.append(
            f'<a class="{active}" href="{href}">'
            f'<span class="tab-icon">{PLATFORM_ICONS[platform]}</span>'
            f'<span>{PLATFORM_LABELS[platform]}</span>'
            f'<span class="tab-count">{counts.get(platform, 0)}</span>'
            "</a>"
        )
    return f'<div class="tabs">{"".join(items)}</div>'


def render_search_bar(
    *,
    action: str,
    active_platform: str,
    query: str,
    primary_label: str,
    primary_href: str,
    secondary_label: Optional[str] = None,
) -> str:
    secondary_button = (
        f'<div class="ghost-chip">{escape(secondary_label)}</div>'
        if secondary_label
        else ""
    )
    return f"""
    <div class="toolbar">
      <form class="search-form" method="get" action="{action}">
        <input type="hidden" name="platform" value="{escape(active_platform)}">
        <div class="search-input-wrap">
          <span class="search-icon">⌕</span>
          <input class="search-input" type="search" name="q" value="{escape(query)}" placeholder="検索...">
        </div>
        <button class="secondary-btn" type="submit">フィルター</button>
      </form>
      {secondary_button}
      <a class="primary-btn" href="{primary_href}">{escape(primary_label)}</a>
    </div>
    """


def render_action_toolbar(primary_label: str, primary_href: str) -> str:
    return (
        '<div class="toolbar">'
        '<div class="ghost-note">月次の出力先スプレッドシートをここで管理します。</div>'
        f'<a class="primary-btn" href="{primary_href}">{escape(primary_label)}</a>'
        "</div>"
    )


def render_accounts_toolbar(active_platform: str, query: str) -> str:
    return f"""
    <div class="toolbar">
      <div class="toolbar-actions">
        <form method="post" action="/accounts/delete-bulk" id="accounts-bulk-form" style="display:inline">
          <input type="hidden" name="platform" value="{escape(active_platform)}">
          <input type="hidden" name="q" value="{escape(query)}">
          <input type="hidden" name="account_ids" id="accounts-bulk-ids" value="">
          <button type="submit" class="secondary-btn" id="accounts-delink-btn" disabled>連携解除</button>
        </form>
        <button class="primary-btn" type="button" data-open-account-link-modal>新しいアカウントを連携</button>
      </div>
    </div>
    <script>
    document.addEventListener('DOMContentLoaded', () => {{
      const selectAllChk = document.getElementById('accounts-select-all');
      const delinkBtn = document.getElementById('accounts-delink-btn');
      const bulkIdsInput = document.getElementById('accounts-bulk-ids');
      const bulkForm = document.getElementById('accounts-bulk-form');
      if (!selectAllChk) return;

      function getBoxes() {{
        return [...document.querySelectorAll('.account-row-check')];
      }}
      function updateState() {{
        const boxes = getBoxes();
        const checked = boxes.filter(b => b.checked);
        delinkBtn.disabled = checked.length === 0;
        bulkIdsInput.value = checked.map(b => b.value).join(',');
        const allChecked = boxes.length > 0 && checked.length === boxes.length;
        selectAllChk.checked = allChecked;
        selectAllChk.indeterminate = checked.length > 0 && !allChecked;
      }}
      selectAllChk.addEventListener('change', () => {{
        const boxes = getBoxes();
        boxes.forEach(b => {{ b.checked = selectAllChk.checked; }});
        updateState();
      }});
      document.addEventListener('change', e => {{
        if (e.target.classList.contains('account-row-check')) updateState();
      }});
      bulkForm.addEventListener('submit', e => {{
        const count = bulkIdsInput.value.split(',').filter(Boolean).length;
        if (!count) {{ e.preventDefault(); return; }}
        if (!confirm(count + ' 件のアカウントの連携を解除しますか？')) e.preventDefault();
      }});
    }});
    </script>
    """


def render_credentials_toolbar(active_platform: str, query: str) -> str:
    reauth_all = (
        '<form method="post" action="/credentials/reauth-all" style="display:inline">'
        '<button class="secondary-btn" type="submit">全て再認証</button>'
        '</form>'
        if active_platform == "meta" else ""
    )
    return f"""
    <div class="toolbar">
      <div class="toolbar-actions">
        {reauth_all}
        <button class="primary-btn" type="button" data-open-platform-select-modal>認証情報を追加</button>
      </div>
    </div>
    """


def render_account_link_modal(
    active_platform: str,
    credential_rows,
    linked_account_rows,
    modal_state: Optional[dict] = None,
) -> str:
    modal_state = modal_state or {}
    selected_platform = modal_state.get("platform", active_platform)
    if selected_platform not in SUPPORTED_PLATFORMS:
        selected_platform = active_platform
    selected_credential_id = str(modal_state.get("credential_profile_id", "")).strip()
    selected_account_ids = {
        str(identifier)
        for identifier in modal_state.get("selected_account_ids", [])
        if str(identifier).strip()
    }
    current_step = int(modal_state.get("step", 1) or 1)
    error_message = modal_state.get("error", "")
    is_open = "true" if modal_state.get("open") else "false"
    hidden_attr = "" if modal_state.get("open") else " hidden"

    credentials_by_platform = {
        platform: [row for row in credential_rows if row["platform"] == platform]
        for platform in SUPPORTED_PLATFORMS
    }
    linked_ids_by_platform = {
        platform: {
            row["account_identifier"]
            for row in linked_account_rows
            if row["platform"] == platform
        }
        for platform in SUPPORTED_PLATFORMS
    }

    platform_cards = []
    for platform in SUPPORTED_PLATFORMS:
        flow = ACCOUNT_LINK_FLOW[platform]
        selected = " selected" if platform == selected_platform else ""
        feature_items = "".join(
            f"<li>{escape(feature)}</li>"
            for feature in flow["features"]
        )
        platform_cards.append(
            f"""
            <button class="platform-choice-card{selected}" type="button" data-platform-choice="{platform}">
              <div class="platform-choice-header">
                <div class="platform-choice-icon">{escape(flow["short_label"][0]) if platform != "meta" else "∞"}</div>
                <div>
                  <h3>{escape(flow["label"])}</h3>
                  <p>{escape(flow["description"])}</p>
                </div>
              </div>
              <ul class="platform-choice-list">
                {feature_items}
              </ul>
            </button>
            """
        )

    auth_panels = []
    account_panels = []
    for platform in SUPPORTED_PLATFORMS:
        flow = ACCOUNT_LINK_FLOW[platform]
        hidden = "" if platform == selected_platform else " hidden"
        credential_items = []
        for row in credentials_by_platform[platform]:
            checked = " checked" if str(row["id"]) == selected_credential_id else ""
            expiry = row["auth_expiry"] or "期限未設定"
            credential_items.append(
                f"""
                <label class="credential-choice-card">
                  <input type="radio" name="credential_profile_choice" value="{row["id"]}" data-platform="{platform}"{checked}>
                  <div class="credential-choice-main">
                    <div class="credential-choice-title">{escape(row["profile_name"])}</div>
                    <div class="credential-choice-meta">{escape(row["profile_identifier"])}</div>
                  </div>
                  <div class="credential-choice-side">
                    <span class="badge green">{escape(row["status"])}</span>
                    <span class="credential-choice-expiry">{escape(expiry)}</span>
                  </div>
                </label>
                """
            )
        if not credential_items:
            credential_items.append(
                f"""
                <div class="credential-empty-state">
                  <p>{escape(flow["label"])} の認証プロフィールがまだありません。</p>
                  <a class="secondary-btn" href="/credentials?platform={platform}">認証情報一覧で追加する</a>
                </div>
                """
            )

        auth_points = "".join(
            f"<li>{escape(point)}</li>"
            for point in flow["auth_points"]
        )
        notice_lines = flow.get("notice_body", [])
        notice_block = ""
        if notice_lines:
            notice_body = "".join(f"<p>{escape(line)}</p>" for line in notice_lines)
            notice_block = f"""
              <div class="auth-notice-card">
                <h3>{escape(flow["notice_title"])}</h3>
                {notice_body}
              </div>"""
        auth_panels.append(
            f"""
            <section class="account-link-stage-panel"{hidden} data-auth-panel="{platform}">
              <div class="account-link-stage-hero">
                <div class="account-link-stage-icon">{escape(flow["short_label"][0]) if platform != "meta" else "∞"}</div>
                <h2>{escape(flow["auth_title"])}</h2>
                <p>{escape(flow["auth_description"])}</p>
              </div>
              <div class="auth-info-card">
                <ul>
                  {auth_points}
                </ul>
              </div>
              <div class="credential-choice-list">
                {''.join(credential_items)}
              </div>
              {notice_block}
            </section>
            """
        )

        pass  # account panels are now rendered dynamically by JS

    modal_error = (
        f'<div class="account-link-error" data-account-link-error>{escape(error_message)}</div>'
        if error_message
        else '<div class="account-link-error" data-account-link-error hidden></div>'
    )

    return f"""
    <div class="account-link-modal-backdrop"{hidden_attr} data-account-link-modal data-open="{is_open}" data-step="{current_step}" data-platform="{escape(selected_platform)}">
      <div class="account-link-modal" role="dialog" aria-modal="true" aria-labelledby="account-link-modal-title">
        <div class="account-link-modal-header">
          <h2 id="account-link-modal-title">広告アカウント連携</h2>
          <button class="account-link-close" type="button" aria-label="閉じる" data-close-account-link-modal>×</button>
        </div>
        <div class="account-link-modal-body">
          <div class="account-link-progress">
            <div class="account-link-progress-line"><span data-account-link-progress-fill></span></div>
            <div class="account-link-progress-steps">
              <div class="account-link-progress-step" data-progress-step="1">
                <span class="account-link-progress-number">1</span>
                <span>プラットフォーム選択</span>
              </div>
              <div class="account-link-progress-step" data-progress-step="2">
                <span class="account-link-progress-number">2</span>
                <span>認証</span>
              </div>
              <div class="account-link-progress-step" data-progress-step="3">
                <span class="account-link-progress-number">3</span>
                <span>アカウント選択</span>
              </div>
            </div>
          </div>
          {modal_error}
          <section class="account-link-step" data-account-link-step="1">
            <div class="account-link-step-header">
              <h3>連携する広告プラットフォームを選択してください</h3>
              <p>選択したプラットフォームの広告アカウントと連携します。</p>
            </div>
            <div class="platform-choice-grid">
              {''.join(platform_cards)}
            </div>
            <div class="account-link-step-actions">
              <button class="secondary-btn" type="button" data-close-account-link-modal>キャンセル</button>
              <button class="primary-btn" type="button" data-next-account-link-step="2">次へ</button>
            </div>
          </section>
          <section class="account-link-step" data-account-link-step="2" hidden>
            {''.join(auth_panels)}
            <div class="account-link-step-actions">
              <button class="secondary-btn" type="button" data-prev-account-link-step="1">戻る</button>
              <button class="primary-btn" type="button" data-next-account-link-step="3" data-auth-continue-button>認証して続行</button>
            </div>
          </section>
          <section class="account-link-step" data-account-link-step="3" hidden>
            <form method="post" action="/accounts/link" data-account-link-submit-form>
              <input type="hidden" name="platform" value="{escape(selected_platform)}" data-account-link-platform-input>
              <input type="hidden" name="credential_profile_id" value="{escape(selected_credential_id)}" data-account-link-credential-input>
              <input type="hidden" name="selected_account_ids" value="" data-account-link-accounts-input>
              <div class="account-link-step-header">
                <h3>連携するアカウントを選択してください</h3>
                <p>認証プロフィール <span data-selected-credential-name>未選択</span> を使って、広告アカウントを追加します。</p>
              </div>
              <div class="account-selection-toolbar">
                <div class="search-input-wrap">
                  <span class="search-icon">⌕</span>
                  <input class="search-input" type="search" placeholder="アカウント名またはIDで検索" data-account-link-search>
                </div>
                <button class="secondary-btn slim" type="button" data-account-link-select-all>全選択</button>
              </div>
              <div class="account-selection-panel">
                <div class="account-link-loading" data-account-link-loading hidden style="padding:2rem;text-align:center;color:#666">取得中...</div>
                <div class="account-link-error" data-account-discover-error hidden style="padding:1rem;color:#c00"></div>
                <div class="account-selection-scroll" data-account-dynamic-list></div>
              </div>
              <div class="account-link-step-actions">
                <button class="secondary-btn" type="button" data-prev-account-link-step="2">戻る</button>
                <button class="primary-btn" type="submit">選択したアカウントを連携</button>
              </div>
            </form>
          </section>
        </div>
      </div>
    </div>
    """


def render_credential_link_modal(
    active_platform: str,
    modal_state: Optional[dict] = None,
) -> str:
    modal_state = modal_state or {}
    selected_platform = (modal_state.get("platform") or active_platform).strip() or active_platform
    if selected_platform not in SUPPORTED_PLATFORMS:
        selected_platform = active_platform
    auth_flow = CREDENTIAL_AUTH_FLOW[selected_platform]
    selected_auth_type = (
        modal_state.get("auth_type")
        or auth_flow["recommended_auth_type"]
    ).strip()
    current_step = int(modal_state.get("step", 1) or 1)
    error_message = modal_state.get("error", "")
    is_open = "true" if modal_state.get("open") else "false"
    hidden_attr = "" if modal_state.get("open") else " hidden"

    platform_cards = []
    auth_panels = []
    for platform in SUPPORTED_PLATFORMS:
        flow = CREDENTIAL_AUTH_FLOW[platform]
        selected = " selected" if platform == selected_platform else ""
        platform_cards.append(
            f"""
            <button class="platform-choice-card{selected}" type="button" data-credential-platform-choice="{platform}">
              <div class="platform-choice-header">
                <div class="platform-choice-icon">{escape(PLATFORM_ICONS[platform])}</div>
                <div>
                  <h3>{escape(PLATFORM_LABELS[platform])}</h3>
                  <p>{escape(ACCOUNT_LINK_FLOW[platform]["description"])}</p>
                </div>
              </div>
            </button>
            """
        )

        method_cards = []
        for method in flow["auth_methods"]:
            checked = (
                " checked"
                if platform == selected_platform and method["value"] == selected_auth_type
                else ""
            )
            notes = "".join(
                f"<li>{escape(note)}</li>"
                for note in method["notes"]
            )
            method_cards.append(
                f"""
                <label class="auth-method-card">
                  <input type="radio" name="credential_auth_type_choice" value="{escape(method["value"])}" data-platform="{platform}"{checked}>
                  <div class="auth-method-body">
                    <div class="auth-method-title">{escape(method["label"])}</div>
                    <p>{escape(method["description"])}</p>
                    <ul class="platform-choice-list">
                      {notes}
                    </ul>
                  </div>
                </label>
                """
            )
        hidden = "" if platform == selected_platform else " hidden"
        auth_panels.append(
            f"""
            <section class="account-link-stage-panel"{hidden} data-credential-auth-panel="{platform}">
              <div class="account-link-stage-hero">
                <div class="account-link-stage-icon">{escape(PLATFORM_ICONS[platform])}</div>
                <h2>{escape(PLATFORM_LABELS[platform])} 認証方式を選択</h2>
                <p>認証情報一覧には、広告アカウント連携に使う主体を保存します。</p>
              </div>
              <div class="auth-method-grid">
                {''.join(method_cards)}
              </div>
            </section>
            """
        )

    modal_error = (
        f'<div class="account-link-error" data-credential-error>{escape(error_message)}</div>'
        if error_message
        else '<div class="account-link-error" data-credential-error hidden></div>'
    )

    return f"""
    <div class="account-link-modal-backdrop"{hidden_attr} data-credential-modal data-open="{is_open}" data-step="{current_step}" data-platform="{escape(selected_platform)}" data-auth-type="{escape(selected_auth_type)}">
      <div class="account-link-modal credential-modal" role="dialog" aria-modal="true" aria-labelledby="credential-modal-title">
        <div class="account-link-modal-header">
          <h2 id="credential-modal-title">認証情報を追加</h2>
          <button class="account-link-close" type="button" aria-label="閉じる" data-close-credential-modal>×</button>
        </div>
        <div class="account-link-modal-body">
          <div class="account-link-progress">
            <div class="account-link-progress-line"><span data-credential-progress-fill></span></div>
            <div class="account-link-progress-steps">
              <div class="account-link-progress-step" data-credential-progress-step="1">
                <span class="account-link-progress-number">1</span>
                <span>プラットフォーム</span>
              </div>
              <div class="account-link-progress-step" data-credential-progress-step="2">
                <span class="account-link-progress-number">2</span>
                <span>認証方式</span>
              </div>
              <div class="account-link-progress-step" data-credential-progress-step="3">
                <span class="account-link-progress-number">3</span>
                <span>プロフィール情報</span>
              </div>
            </div>
          </div>
          {modal_error}
          <section class="account-link-step" data-credential-step="1">
            <div class="account-link-step-header">
              <h3>認証を追加するプラットフォームを選択してください</h3>
              <p>Google アカウント、Meta のビジネスマネージャー、TikTok の認証主体をここで管理します。</p>
            </div>
            <div class="platform-choice-grid compact">
              {''.join(platform_cards)}
            </div>
            <div class="account-link-step-actions">
              <button class="secondary-btn" type="button" data-close-credential-modal>キャンセル</button>
              <button class="primary-btn" type="button" data-next-credential-step="2">次へ</button>
            </div>
          </section>
          <section class="account-link-step" data-credential-step="2" hidden>
            {''.join(auth_panels)}
            <div class="account-link-step-actions">
              <button class="secondary-btn" type="button" data-prev-credential-step="1">戻る</button>
              <button class="primary-btn" type="button" data-next-credential-step="3">次へ</button>
            </div>
          </section>
          <section class="account-link-step" data-credential-step="3" hidden>
            <form method="post" action="/credentials/new" data-credential-submit-form class="credential-modal-form">
              <input type="hidden" name="platform" value="{escape(selected_platform)}" data-credential-platform-input>
              <input type="hidden" name="auth_type" value="{escape(selected_auth_type)}" data-credential-auth-type-input>
              <div class="account-link-step-header">
                <h3>認証プロフィール情報を入力してください</h3>
                <p><span data-credential-selected-platform>{escape(PLATFORM_LABELS[selected_platform])}</span> / <span data-credential-selected-auth>{escape(AUTH_TYPE_LABELS.get(selected_auth_type, selected_auth_type))}</span> として保存されます。</p>
              </div>
              <div class="credential-form-grid">
                <label data-system-user-token-field hidden style="grid-column:1/-1">アクセストークン <span class="required-mark">*</span>
                  <textarea name="access_token" rows="3" placeholder="EAAB..." data-credential-access-token autocomplete="off" style="font-family:monospace;font-size:0.85em;resize:vertical"></textarea>
                  <small style="color:#666">Meta Business Suite → 設定 → ユーザー → システムユーザーで発行したトークンを貼り付けてください。</small>
                </label>
                <label>認証プロフィール名
                  <input type="text" name="profile_name" value="{escape(modal_state.get('profile_name', ''))}" placeholder="例: DYMFRED003 / ながもと" data-credential-profile-name>
                </label>
                <label>認証プロフィールID
                  <input type="text" name="profile_identifier" value="{escape(modal_state.get('profile_identifier', ''))}" placeholder="メールアドレスや管理ID" data-credential-profile-identifier>
                </label>
                <label>作成者メール
                  <input type="email" name="creator_email" value="{escape(modal_state.get('creator_email', ''))}" required>
                </label>
                <label>認証期限
                  <input type="text" name="auth_expiry" value="{escape(modal_state.get('auth_expiry', ''))}" placeholder="2026-05-31 12:00">
                </label>
                <label>外部ユーザーID
                  <input type="text" name="external_user_id" value="{escape(modal_state.get('external_user_id', ''))}" placeholder="OAuth の sub / Meta user id など">
                </label>
                <label>トークン失効日時
                  <input type="text" name="token_expires_at" value="{escape(modal_state.get('token_expires_at', ''))}" placeholder="2026-05-31 12:00">
                </label>
              </div>
              <div class="account-link-step-actions">
                <button class="secondary-btn" type="button" data-prev-credential-step="2">戻る</button>
                <button class="primary-btn" type="submit" data-credential-submit-button>認証情報を保存</button>
              </div>
            </form>
          </section>
        </div>
      </div>
    </div>
    """


def render_platform_select_modal() -> str:
    return """
    <div class="account-link-modal-backdrop" id="platform-select-modal" hidden role="dialog" aria-modal="true" aria-labelledby="platform-select-title">
      <div class="account-link-modal" style="max-width:420px">
        <div class="account-link-modal-header">
          <h2 id="platform-select-title">認証情報を追加</h2>
          <button class="account-link-close" type="button" id="platform-select-close">×</button>
        </div>
        <div class="account-link-modal-body" style="padding:1.5rem">
          <p style="margin:0 0 1.25rem;color:#555">認証するプラットフォームを選択してください。</p>
          <div class="platform-choice-grid compact" style="margin-bottom:1.5rem">
            <button type="button" class="platform-choice-card" data-platform-select="meta">
              <span class="platform-choice-icon">∞</span>
              <span class="platform-choice-label">Meta</span>
            </button>
            <button type="button" class="platform-choice-card" data-platform-select="google">
              <span class="platform-choice-icon">G</span>
              <span class="platform-choice-label">Google</span>
            </button>
            <button type="button" class="platform-choice-card" data-platform-select="tiktok">
              <span class="platform-choice-icon">♪</span>
              <span class="platform-choice-label">TikTok</span>
            </button>
          </div>
          <form method="post" action="/credentials/new" id="platform-select-form">
            <input type="hidden" name="auth_type" value="oauth">
            <input type="hidden" name="platform" id="platform-select-value" value="">
            <div style="display:flex;justify-content:flex-end;gap:.75rem">
              <button type="button" class="secondary-btn" id="platform-select-cancel">キャンセル</button>
              <button type="submit" class="primary-btn" id="platform-select-ok" disabled>OK</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    <script>
    (() => {
      const modal = document.getElementById('platform-select-modal');
      const openBtns = document.querySelectorAll('[data-open-platform-select-modal]');
      const closeBtn = document.getElementById('platform-select-close');
      const cancelBtn = document.getElementById('platform-select-cancel');
      const okBtn = document.getElementById('platform-select-ok');
      const platformInput = document.getElementById('platform-select-value');
      const platformCards = modal.querySelectorAll('[data-platform-select]');

      function openModal() { modal.hidden = false; document.body.classList.add('modal-open'); }
      function closeModal() {
        modal.hidden = true;
        document.body.classList.remove('modal-open');
        platformCards.forEach(c => c.classList.remove('selected'));
        platformInput.value = '';
        okBtn.disabled = true;
      }

      openBtns.forEach(b => b.addEventListener('click', openModal));
      closeBtn.addEventListener('click', closeModal);
      cancelBtn.addEventListener('click', closeModal);
      modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
      document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) closeModal(); });

      platformCards.forEach(card => {
        card.addEventListener('click', () => {
          platformCards.forEach(c => c.classList.remove('selected'));
          card.classList.add('selected');
          platformInput.value = card.dataset.platformSelect;
          okBtn.disabled = false;
        });
      });
    })();
    </script>
    """


def render_credential_modal_script() -> str:
    return """
    <script>
    (() => {
      const modal = document.querySelector('[data-credential-modal]');
      if (!modal) return;

      const body = document.body;
      const openButtons = document.querySelectorAll('[data-open-credential-modal]');
      const closeButtons = modal.querySelectorAll('[data-close-credential-modal]');
      const stepSections = modal.querySelectorAll('[data-credential-step]');
      const progressSteps = modal.querySelectorAll('[data-credential-progress-step]');
      const progressFill = modal.querySelector('[data-credential-progress-fill]');
      const platformButtons = modal.querySelectorAll('[data-credential-platform-choice]');
      const authPanels = modal.querySelectorAll('[data-credential-auth-panel]');
      const authRadios = modal.querySelectorAll('input[name="credential_auth_type_choice"]');
      const errorBox = modal.querySelector('[data-credential-error]');
      const platformInput = modal.querySelector('[data-credential-platform-input]');
      const authTypeInput = modal.querySelector('[data-credential-auth-type-input]');
      const selectedPlatformLabel = modal.querySelector('[data-credential-selected-platform]');
      const selectedAuthLabel = modal.querySelector('[data-credential-selected-auth]');
      const submitButton = modal.querySelector('[data-credential-submit-button]');
      const profileNameInput = modal.querySelector('[data-credential-profile-name]');
      const profileIdentifierInput = modal.querySelector('[data-credential-profile-identifier]');
      const accessTokenLabel = modal.querySelector('[data-system-user-token-field]');
      const accessTokenInput = modal.querySelector('[data-credential-access-token]');
      let isOpen = modal.dataset.open === 'true';
      let currentStep = Number(modal.dataset.step || '1');
      let selectedPlatform = modal.dataset.platform || 'meta';
      let selectedAuthType = modal.dataset.authType || 'oauth';

      const authTypeLabels = {
        oauth: 'OAuth連携',
        service_account: 'サービスアカウント',
        system_user: 'System User'
      };

      function clearError() {
        errorBox.textContent = '';
        errorBox.hidden = true;
      }

      function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
      }

      function selectedAuthRadio() {
        return modal.querySelector(`input[name="credential_auth_type_choice"][data-platform="${selectedPlatform}"]:checked`);
      }

      function updateView() {
        modal.hidden = !isOpen;
        body.classList.toggle('modal-open', isOpen);
        stepSections.forEach((section) => {
          section.hidden = Number(section.dataset.credentialStep) !== currentStep;
        });
        progressSteps.forEach((step) => {
          const stepNumber = Number(step.dataset.credentialProgressStep);
          step.classList.toggle('active', stepNumber === currentStep);
          step.classList.toggle('done', stepNumber < currentStep);
        });
        progressFill.style.width = `${((currentStep - 1) / 2) * 100}%`;
        platformButtons.forEach((button) => {
          button.classList.toggle('selected', button.dataset.credentialPlatformChoice === selectedPlatform);
        });
        authPanels.forEach((panel) => {
          panel.hidden = panel.dataset.credentialAuthPanel !== selectedPlatform;
        });
        platformInput.value = selectedPlatform;
        const selectedAuth = selectedAuthRadio();
        if (selectedAuth) {
          selectedAuthType = selectedAuth.value;
        }
        authTypeInput.value = selectedAuthType;
        selectedPlatformLabel.textContent = selectedPlatform === 'meta' ? 'Meta' : selectedPlatform === 'google' ? 'Google' : 'TikTok';
        selectedAuthLabel.textContent = authTypeLabels[selectedAuthType] || selectedAuthType;
        submitButton.textContent = selectedAuthType === 'oauth' ? 'OAuthで認証に進む' : '認証情報を保存';
        const requiresProfileFields = selectedAuthType !== 'oauth';
        profileNameInput.required = requiresProfileFields;
        profileIdentifierInput.required = requiresProfileFields;
        const isSystemUser = selectedAuthType === 'system_user';
        if (accessTokenLabel) accessTokenLabel.hidden = !isSystemUser;
        if (accessTokenInput) accessTokenInput.required = isSystemUser;
      }

      function openModal() {
        isOpen = true;
        clearError();
        updateView();
      }

      function closeModal() {
        isOpen = false;
        updateView();
      }

      function goToStep(stepNumber) {
        currentStep = stepNumber;
        clearError();
        updateView();
      }

      openButtons.forEach((button) => button.addEventListener('click', openModal));
      closeButtons.forEach((button) => button.addEventListener('click', closeModal));

      modal.addEventListener('click', (event) => {
        if (event.target === modal) {
          closeModal();
        }
      });

      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && isOpen) {
          closeModal();
        }
      });

      platformButtons.forEach((button) => {
        button.addEventListener('click', () => {
          selectedPlatform = button.dataset.credentialPlatformChoice;
          const firstRadio = modal.querySelector(`input[name="credential_auth_type_choice"][data-platform="${selectedPlatform}"]`);
          if (firstRadio) {
            firstRadio.checked = true;
            selectedAuthType = firstRadio.value;
          }
          clearError();
          updateView();
        });
      });

      authRadios.forEach((radio) => {
        radio.addEventListener('change', () => {
          selectedPlatform = radio.dataset.platform;
          selectedAuthType = radio.value;
          clearError();
          updateView();
        });
      });

      modal.querySelector('[data-next-credential-step="2"]').addEventListener('click', () => {
        goToStep(2);
      });

      modal.querySelector('[data-next-credential-step="3"]').addEventListener('click', () => {
        const authRadio = selectedAuthRadio();
        if (!authRadio) {
          showError('認証方式を選択してください。');
          return;
        }
        selectedAuthType = authRadio.value;
        goToStep(3);
      });

      modal.querySelectorAll('[data-prev-credential-step]').forEach((button) => {
        button.addEventListener('click', () => {
          goToStep(Number(button.dataset.prevCredentialStep));
        });
      });

      updateView();
    })();
    </script>
    """


def render_account_link_modal_script() -> str:
    return """
    <script>
    (() => {
      const modal = document.querySelector('[data-account-link-modal]');
      if (!modal) return;

      const body = document.body;
      const openButtons = document.querySelectorAll('[data-open-account-link-modal]');
      const closeButtons = modal.querySelectorAll('[data-close-account-link-modal]');
      const stepSections = modal.querySelectorAll('[data-account-link-step]');
      const progressSteps = modal.querySelectorAll('[data-progress-step]');
      const progressFill = modal.querySelector('[data-account-link-progress-fill]');
      const platformButtons = modal.querySelectorAll('[data-platform-choice]');
      const authPanels = modal.querySelectorAll('[data-auth-panel]');
      const credentialRadios = modal.querySelectorAll('input[name="credential_profile_choice"]');
      const searchInput = modal.querySelector('[data-account-link-search]');
      const selectAllButton = modal.querySelector('[data-account-link-select-all]');
      const submitForm = modal.querySelector('[data-account-link-submit-form]');
      const platformInput = modal.querySelector('[data-account-link-platform-input]');
      const credentialInput = modal.querySelector('[data-account-link-credential-input]');
      const accountsInput = modal.querySelector('[data-account-link-accounts-input]');
      const errorBox = modal.querySelector('[data-account-link-error]');
      const selectedCredentialName = modal.querySelector('[data-selected-credential-name]');
      const authContinueButton = modal.querySelector('[data-auth-continue-button]');
      const dynamicList = modal.querySelector('[data-account-dynamic-list]');
      const loadingEl = modal.querySelector('[data-account-link-loading]');
      const discoverErrorEl = modal.querySelector('[data-account-discover-error]');

      const accountCache = {};
      let activeRequestKey = '';
      let isOpen = modal.dataset.open === 'true';
      let currentStep = Number(modal.dataset.step || '1');
      let selectedPlatform = modal.dataset.platform || 'meta';

      function clearError() {
        if (!errorBox) return;
        errorBox.textContent = '';
        errorBox.hidden = true;
      }

      function showError(message) {
        if (!errorBox) return;
        errorBox.textContent = message;
        errorBox.hidden = false;
      }

      function selectedCredential() {
        return modal.querySelector(`input[name="credential_profile_choice"][data-platform="${selectedPlatform}"]:checked`);
      }

      function escapeHtml(value) {
        return String(value || '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      }

      function renderAccountRows(accounts) {
        discoverErrorEl.hidden = true;
        if (!accounts.length) {
          dynamicList.innerHTML = '<div class="account-selection-empty">連携できる広告アカウントが見つかりませんでした。</div>';
          applySearch();
          updateSelectAllLabel();
          return;
        }
        dynamicList.innerHTML = accounts.map((account) => {
          const accountId = String(account.account_id || '').trim();
          const accountName = String(account.account_name || accountId).trim();
          const searchText = `${accountName} ${accountId}`.toLowerCase();
          const isLinked = !!account.is_linked;
          return `
            <label class="account-choice-row" data-account-search="${escapeHtml(searchText)}">
              <input type="checkbox" value="${escapeHtml(accountId)}" data-platform="${escapeHtml(selectedPlatform)}"${isLinked ? ' disabled' : ''}>
              <div class="account-choice-main">
                <div class="account-choice-title">${escapeHtml(accountName)}</div>
                <div class="account-choice-meta">${escapeHtml(accountId)}</div>
              </div>
              <div class="account-choice-side">
                ${isLinked ? '<span class="badge warn">連携済み</span>' : ''}
              </div>
            </label>
          `;
        }).join('');
        applySearch();
        updateSelectAllLabel();
      }

      function loadAccounts() {
        const credential = selectedCredential();
        if (!credential) return;
        const cacheKey = `${selectedPlatform}:${credential.value}`;
        if (accountCache[cacheKey]) {
          renderAccountRows(accountCache[cacheKey]);
          return;
        }
        if (activeRequestKey === cacheKey) return;
        activeRequestKey = cacheKey;
        dynamicList.innerHTML = '';
        loadingEl.hidden = false;
        discoverErrorEl.hidden = true;
        const params = new URLSearchParams({ platform: selectedPlatform, credential_id: credential.value });
        fetch(`/api/accounts/discover?${params}`)
          .then(async (res) => {
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.error) throw new Error(data.error || 'アカウント取得に失敗しました。');
            accountCache[cacheKey] = data.accounts || [];
            if (activeRequestKey === cacheKey) {
              renderAccountRows(accountCache[cacheKey]);
            }
          })
          .catch((err) => {
            discoverErrorEl.textContent = err.message;
            discoverErrorEl.hidden = false;
          })
          .finally(() => {
            loadingEl.hidden = true;
            if (activeRequestKey === cacheKey) activeRequestKey = '';
          });
      }

      function updateCredentialSummary() {
        const credential = selectedCredential();
        selectedCredentialName.textContent = credential
          ? credential.closest('.credential-choice-card').querySelector('.credential-choice-title').textContent
          : '未選択';
        credentialInput.value = credential ? credential.value : '';
      }

      function applySearch() {
        const term = (searchInput.value || '').trim().toLowerCase();
        dynamicList.querySelectorAll('.account-choice-row').forEach((row) => {
          row.hidden = term ? !(row.dataset.accountSearch || '').includes(term) : false;
        });
      }

      function updateSelectAllLabel() {
        const boxes = [...dynamicList.querySelectorAll('input[type="checkbox"]:not(:disabled)')].filter((b) => !b.closest('.account-choice-row').hidden);
        if (!boxes.length) { selectAllButton.textContent = '全選択'; return; }
        selectAllButton.textContent = boxes.every((b) => b.checked) ? '選択解除' : '全選択';
      }

      function updateView() {
        modal.hidden = !isOpen;
        body.classList.toggle('modal-open', isOpen);
        stepSections.forEach((section) => {
          section.hidden = Number(section.dataset.accountLinkStep) !== currentStep;
        });
        progressSteps.forEach((step) => {
          const n = Number(step.dataset.progressStep);
          step.classList.toggle('active', n === currentStep);
          step.classList.toggle('done', n < currentStep);
        });
        progressFill.style.width = `${((currentStep - 1) / 2) * 100}%`;
        platformButtons.forEach((btn) => {
          btn.classList.toggle('selected', btn.dataset.platformChoice === selectedPlatform);
        });
        authPanels.forEach((panel) => {
          panel.hidden = panel.dataset.authPanel !== selectedPlatform;
        });
        platformInput.value = selectedPlatform;
        updateCredentialSummary();
        authContinueButton.disabled = !selectedCredential();
        applySearch();
        updateSelectAllLabel();
        if (currentStep === 3 && selectedCredential()) {
          loadAccounts();
        }
      }

      function openModal() { isOpen = true; clearError(); updateView(); }
      function closeModal() { isOpen = false; updateView(); }
      function goToStep(n) { currentStep = n; clearError(); updateView(); }

      platformButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
          selectedPlatform = btn.dataset.platformChoice;
          searchInput.value = '';
          clearError();
          updateView();
        });
      });

      credentialRadios.forEach((radio) => {
        radio.addEventListener('change', () => {
          selectedPlatform = radio.dataset.platform;
          clearError();
          updateView();
        });
      });

      openButtons.forEach((btn) => btn.addEventListener('click', openModal));
      closeButtons.forEach((btn) => btn.addEventListener('click', closeModal));

      modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
      document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && isOpen) closeModal(); });

      modal.querySelector('[data-next-account-link-step="2"]').addEventListener('click', () => goToStep(2));

      modal.querySelector('[data-next-account-link-step="3"]').addEventListener('click', () => {
        if (!selectedCredential()) { showError('認証プロフィールを選択してください。'); return; }
        goToStep(3);
      });

      modal.querySelectorAll('[data-prev-account-link-step]').forEach((btn) => {
        btn.addEventListener('click', () => goToStep(Number(btn.dataset.prevAccountLinkStep)));
      });

      searchInput.addEventListener('input', () => { applySearch(); updateSelectAllLabel(); });

      selectAllButton.addEventListener('click', () => {
        const boxes = [...dynamicList.querySelectorAll('input[type="checkbox"]:not(:disabled)')].filter((b) => !b.closest('.account-choice-row').hidden);
        if (!boxes.length) return;
        const allChecked = boxes.every((b) => b.checked);
        boxes.forEach((b) => { b.checked = !allChecked; });
        updateSelectAllLabel();
      });

      dynamicList.addEventListener('change', (e) => {
        if (e.target.matches('input[type="checkbox"]')) updateSelectAllLabel();
      });

      submitForm.addEventListener('submit', (e) => {
        const credential = selectedCredential();
        if (!credential) {
          e.preventDefault(); showError('認証プロフィールを選択してください。'); goToStep(2); return;
        }
        const selected = [...dynamicList.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)')].map((b) => b.value);
        if (!selected.length) {
          e.preventDefault(); showError('連携する広告アカウントを1件以上選択してください。'); return;
        }
        platformInput.value = selectedPlatform;
        credentialInput.value = credential.value;
        accountsInput.value = selected.join(',');
      });

      updateView();
    })();
    </script>
    """


def render_rule_condition(row) -> str:
    return (
        f'{escape(row["metric_name"])} '
        f'{escape(row["condition_operator"])} '
        f'{escape(row["threshold_value"])}'
    )


def render_rule_action(row) -> str:
    if row["action_value"]:
        return f'{escape(row["action_type"])}: {escape(row["action_value"])}'
    return escape(row["action_type"])


def _sync_panel_html(title: str, status_label: str, action_html: str) -> str:
    return f"""
    <section class="sync-panel">
      <div>
        <h2>{title}</h2>
        <p>{escape(status_label)}</p>
      </div>
      {action_html}
    </section>
    """


def _sync_form_html(action: str, sync_date: str, btn_label: str) -> str:
    return f"""
    <form class="sync-form" method="post" action="{action}">
      <label>対象日
        <input type="date" name="report_date" value="{escape(sync_date)}">
      </label>
      <button class="primary-btn" type="submit">{btn_label}</button>
    </form>
    """


def render_meta_sync_panel(active_platform: str, sync_settings, sync_date: str) -> str:
    merged = merged_integration_settings(sync_settings)
    has_sheet = bool(
        merged["google_service_account_file"].strip()
        and (
            merged["google_reports_folder_id"].strip()
            or merged["google_spreadsheet_id"].strip()
        )
    )
    status_label = (
        "Google Sheets の設定は保存済みです。Meta は連携済み認証プロフィールのトークンを優先して使い、キャンペーン一覧タブへ反映します。"
        if has_sheet
        else "同期前に Google サービスアカウント JSON と、保存先フォルダID または既存スプレッドシートID を設定してください。"
    )
    action_html = (
        _sync_form_html("/accounts/meta/sync", sync_date, "指定日の数値をキャンペーン一覧へ反映")
        if has_sheet
        else '<a class="primary-btn" href="/settings">設定を入力する</a>'
    )
    return _sync_panel_html("Meta 数値をキャンペーン一覧へ反映", status_label, action_html)


def render_google_sync_panel(sync_settings, sync_date: str) -> str:
    merged = merged_integration_settings(sync_settings)
    has_sheet = bool(
        merged["google_service_account_file"].strip()
        and (
            merged["google_reports_folder_id"].strip()
            or merged["google_spreadsheet_id"].strip()
        )
    )
    status_label = (
        "Google Sheets の設定は保存済みです。Google 広告は連携済み認証プロフィールのトークンを優先して使い、キャンペーン一覧タブへ反映します。"
        if has_sheet
        else "同期前に Google サービスアカウント JSON と、保存先フォルダID または既存スプレッドシートID を設定してください。"
    )
    action_html = (
        _sync_form_html("/accounts/google/sync", sync_date, "指定日の数値をキャンペーン一覧へ反映")
        if has_sheet
        else '<a class="primary-btn" href="/settings">設定を入力する</a>'
    )
    return _sync_panel_html("Google 広告 数値をキャンペーン一覧へ反映", status_label, action_html)


def render_tiktok_sync_panel(sync_settings, sync_date: str) -> str:
    merged = merged_integration_settings(sync_settings)
    has_sheet = bool(
        merged["google_service_account_file"].strip()
        and (
            merged["google_reports_folder_id"].strip()
            or merged["google_spreadsheet_id"].strip()
        )
    )
    status_label = (
        "Google Sheets の設定は保存済みです。TikTok は連携済み認証プロフィールのトークンを優先して使い、キャンペーン一覧タブへ反映します。"
        if has_sheet
        else "同期前に Google サービスアカウント JSON と、保存先フォルダID または既存スプレッドシートID を設定してください。"
    )
    action_html = (
        _sync_form_html("/accounts/tiktok/sync", sync_date, "指定日の数値をキャンペーン一覧へ反映")
        if has_sheet
        else '<a class="primary-btn" href="/settings">設定を入力する</a>'
    )
    return _sync_panel_html("TikTok 広告 数値をキャンペーン一覧へ反映", status_label, action_html)


def render_monthly_campaign_sync_panel(sync_settings, sync_date: str) -> str:
    merged = merged_integration_settings(sync_settings)
    has_required_settings = bool(
        merged["meta_access_token"].strip()
        and merged["google_service_account_file"].strip()
        and merged["google_reports_folder_id"].strip()
    )
    status_label = (
        "Meta と共有ドライブの設定は保存済みです。指定日の消化キャンペーンを月次スプシへ反映できます。"
        if has_required_settings
        else "同期前に設定画面で Meta アクセストークン、Google サービスアカウント JSON、共有ドライブ配下のレポートフォルダID を入れてください。"
    )
    action_html = (
        f"""
        <form class="sync-form" method="post" action="/accounts/meta/monthly-sync">
          <label>対象日
            <input type="date" name="report_date" value="{escape(sync_date)}">
          </label>
          <button class="primary-btn" type="submit">消化キャンペーンを月次スプシへ転記</button>
        </form>
        """
        if has_required_settings
        else '<a class="primary-btn" href="/settings">設定を入力する</a>'
    )
    return f"""
    <section class="sync-panel">
      <div>
        <h2>Meta 消化キャンペーンを月次スプシへ転記</h2>
        <p>{escape(status_label)}</p>
        <div class="sync-meta">
          <span>保存先フォルダ: {escape(merged["google_reports_folder_id"] or "未設定")}</span>
          <span>初期タブ名: {escape(merged["google_monthly_report_sheet_tab_name"])}</span>
        </div>
      </div>
      {action_html}
    </section>
    """




def render_rules_page(
    rows,
    counts,
    active_platform: str,
    query: str,
    *,
    notice: str = "",
    error: str = "",
    current_user: Optional[dict] = None,
) -> bytes:
    header = """
    <section class="page-head">
      <div>
        <h1>自動運用ルール</h1>
        <p>媒体ごとの自動化ルールを一覧で管理します。条件と実行内容を先に定義しておくことで、運用の属人化を減らせます。</p>
      </div>
    </section>
    """
    tabs = render_tabs("/rules", active_platform, counts, query)
    toolbar = render_search_bar(
        action="/rules",
        active_platform=active_platform,
        query=query,
        primary_label="新しいルールを追加",
        primary_href=f"/rules/new?platform={escape(active_platform)}",
        secondary_label="条件・担当者で検索",
    )
    table_rows = []
    for row in rows:
        status_class = (
            "green"
            if row["status"] == "有効"
            else "warn"
            if row["status"] == "下書き"
            else "red"
        )
        table_rows.append(
            f"""
            <tr>
              <td><span class="platform-mark">{PLATFORM_ICONS[row["platform"]]}</span>{escape(row["rule_name"])}</td>
              <td>{escape(row["target_label"])}</td>
              <td>{render_rule_condition(row)}</td>
              <td>{render_rule_action(row)}</td>
              <td><span class="badge {status_class}">{escape(row["status"])}</span></td>
              <td><span class="pill">{escape(row["owner_email"])}</span></td>
              <td>{escape(row["updated_at"])}</td>
              <td class="action-cell">
                <form method="post" action="/rules/{row["id"]}/delete?platform={escape(active_platform)}&q={escape(query)}">
                  <button class="danger-link outlined" type="submit">削除</button>
                </form>
              </td>
            </tr>
            """
        )
    body = f"""
    {header}
    {render_feedback(notice, error)}
    <section class="card">
      {toolbar}
      {tabs}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ルール名</th>
              <th>対象</th>
              <th>発火条件</th>
              <th>実行内容</th>
              <th>ステータス</th>
              <th>担当者</th>
              <th>更新日時</th>
              <th>アクション</th>
            </tr>
          </thead>
          <tbody>
            {''.join(table_rows) if table_rows else '<tr><td colspan="8" class="empty">該当するルールがありません。</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
    """
    return render_layout("自動運用ルール", body, "/rules", current_user)


def render_rule_form(
    active_platform: str,
    *,
    error: str = "",
    values: Optional[dict] = None,
) -> bytes:
    values = values or {}
    selected_platform = (values.get("platform") or active_platform).strip() or active_platform
    operator = (values.get("condition_operator") or ">=").strip() or ">="
    action_type = (values.get("action_type") or "通知").strip() or "通知"
    status = (values.get("status") or "有効").strip() or "有効"
    owner_email = (values.get("owner_email") or "").strip()
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    body = f"""
    <section class="page-head compact">
      <div>
        <a class="back-link" href="/rules?platform={escape(selected_platform)}">← 自動運用ルールに戻る</a>
        <h1>新しい自動運用ルールを追加</h1>
        <p>まずは手動登録で、判断条件とアクションの型を FredCore 上に揃えられるようにしています。</p>
      </div>
    </section>
    <section class="card form-card">
      {error_html}
      <form method="post" action="/rules/new">
        <label>プラットフォーム
          <select name="platform">
            {render_platform_options(selected_platform)}
          </select>
        </label>
        <label>ルール名
          <input type="text" name="rule_name" value="{escape(values.get('rule_name', ''))}" placeholder="CPA 悪化時に Slack 通知" required>
        </label>
        <label>対象アカウント / キャンペーン
          <input type="text" name="target_label" value="{escape(values.get('target_label', ''))}" placeholder="fred_meta_main" required>
        </label>
        <label>評価指標
          <input type="text" name="metric_name" value="{escape(values.get('metric_name', ''))}" placeholder="CPA / CTR / 消化率" required>
        </label>
        <label>条件
          <select name="condition_operator">
            {render_keyed_options(RULE_OPERATOR_OPTIONS, operator)}
          </select>
        </label>
        <label>しきい値
          <input type="text" name="threshold_value" value="{escape(values.get('threshold_value', ''))}" placeholder="8000" required>
        </label>
        <label>実行アクション
          <select name="action_type">
            {render_keyed_options(RULE_ACTION_OPTIONS, action_type)}
          </select>
        </label>
        <label>アクション詳細
          <input type="text" name="action_value" value="{escape(values.get('action_value', ''))}" placeholder="Slack #ad-alerts / -15%">
        </label>
        <label>ステータス
          <select name="status">
            {render_keyed_options(RULE_STATUS_OPTIONS, status)}
          </select>
        </label>
        <label>担当者メール
          <input type="email" name="owner_email" value="{escape(owner_email)}" required>
        </label>
        <label>補足メモ
          <input type="text" name="notes" value="{escape(values.get('notes', ''))}" placeholder="通知先や背景を簡単にメモ">
        </label>
        <div class="form-actions">
          <a class="secondary-btn" href="/rules?platform={escape(selected_platform)}">キャンセル</a>
          <button class="primary-btn" type="submit">ルールを保存</button>
        </div>
      </form>
    </section>
    """
    return render_layout("自動運用ルールを追加", body, "/rules")


def render_accounts_page(
    rows,
    counts,
    active_platform: str,
    query: str,
    *,
    notice: str = "",
    error: str = "",
    sync_settings=None,
    sync_date: str = "",
    credential_rows=(),
    linked_account_rows=(),
    account_link_modal_state: Optional[dict] = None,
    current_user: Optional[dict] = None,
) -> bytes:
    header = """
    <section class="page-head">
      <div>
        <h1>アカウント連携</h1>
        <p>自動運用や自動入稿で使用できるアカウントを追加したり、今連携しているアカウントが誰の認証情報で動いているかを確認するページです。</p>
      </div>
    </section>
    """
    tabs = render_tabs("/accounts", active_platform, counts, query)
    toolbar = render_accounts_toolbar(active_platform, query)
    table_rows = []
    for row in rows:
        table_rows.append(
            f"""
            <tr>
              <td class="checkbox-cell"><input type="checkbox" class="account-row-check" value="{row["id"]}"></td>
              <td><span class="platform-mark">{PLATFORM_ICONS[row["platform"]]}</span>{escape(row["account_name"])}</td>
              <td><span class="badge green">{escape(row["credential_profile_name"] or "-")}</span></td>
              <td style="white-space:nowrap">{escape(row["operator_email"])}</td>
              <td>{escape(row["parent_account"])}</td>
              <td class="action-cell">
                <form method="post" action="/accounts/{row["id"]}/delete?platform={escape(active_platform)}&q={escape(query)}">
                  <button class="danger-link" type="submit">削除</button>
                </form>
              </td>
            </tr>
            """
        )
    sync_panel = ""
    if sync_settings is not None:
        if active_platform == "meta":
            sync_panel = render_meta_sync_panel(active_platform, sync_settings, sync_date)
        elif active_platform == "google":
            sync_panel = render_google_sync_panel(sync_settings, sync_date)
        elif active_platform == "tiktok":
            sync_panel = render_tiktok_sync_panel(sync_settings, sync_date)
    account_link_modal = render_account_link_modal(
        active_platform,
        credential_rows,
        linked_account_rows,
        account_link_modal_state,
    )

    body = f"""
    {header}
    {render_feedback(notice, error)}
    {sync_panel}
    <section class="card">
      {toolbar}
      {tabs}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th class="checkbox-cell"><input type="checkbox" id="accounts-select-all"></th>
              <th>アカウント名</th>
              <th>認証プロフィール</th>
              <th>操作担当者</th>
              <th>親アカウント</th>
              <th>アクション</th>
            </tr>
          </thead>
          <tbody>
            {''.join(table_rows) if table_rows else '<tr><td colspan="6" class="empty">該当するアカウントがありません。</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
    {account_link_modal}
    {render_account_link_modal_script()}
    """
    return render_layout("アカウント連携", body, "/accounts", current_user)


def render_credentials_page(
    rows,
    counts,
    active_platform: str,
    query: str,
    *,
    notice: str = "",
    error: str = "",
    credential_modal_state: Optional[dict] = None,
    current_user: Optional[dict] = None,
) -> bytes:
    header = """
    <section class="page-head">
      <div>
        <h1>認証情報一覧</h1>
        <p>プラットフォームに接続するための認証情報を管理します。再認証や不要な認証情報の削除が可能です。</p>
      </div>
    </section>
    """
    tabs = render_tabs("/credentials", active_platform, counts, query)
    toolbar = render_credentials_toolbar(active_platform, query)
    table_rows = []
    for row in rows:
        table_rows.append(
            f"""
            <tr>
              <td>{escape(row["profile_name"])}</td>
              <td><span class="badge green">{escape(row["status"])}</span></td>
              <td>{_fmt_date(str(row["auth_expiry"] or ""))}</td>
              <td style="white-space:nowrap">{escape(row["creator_email"])}</td>
              <td style="white-space:nowrap">{_fmt_datetime(str(row["created_at"] or ""))}</td>
              <td class="action-cell" style="white-space:nowrap">
                <form method="post" action="/credentials/{row["id"]}/reauth?platform={escape(active_platform)}&q={escape(query)}" style="display:inline">
                  <button class="secondary-btn slim" type="submit">再認証</button>
                </form>
                <form method="post" action="/credentials/{row["id"]}/delete?platform={escape(active_platform)}&q={escape(query)}" style="display:inline">
                  <button class="danger-link outlined" type="submit">削除</button>
                </form>
              </td>
            </tr>
            """
        )
    body = f"""
    {header}
    {render_feedback(notice, error)}
    <section class="card">
      {toolbar}
      {tabs}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>認証プロフィール</th>
              <th>ステータス</th>
              <th>認証期限</th>
              <th>作成者</th>
              <th>作成日時</th>
              <th>アクション</th>
            </tr>
          </thead>
          <tbody>
            {''.join(table_rows) if table_rows else '<tr><td colspan="6" class="empty">該当する認証情報がありません。</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
    {render_platform_select_modal()}
    {render_credential_link_modal(active_platform, credential_modal_state)}
    {render_credential_modal_script()}
    """
    return render_layout("認証情報一覧", body, "/credentials", current_user)


def render_account_form(
    active_platform: str,
    credentials,
    error: str = "",
    values: Optional[dict] = None,
) -> bytes:
    values = values or {}
    selected_platform = (values.get("platform") or active_platform).strip() or active_platform
    selected_credential_profile_id = str(values.get("credential_profile_id", "")).strip()
    options = ['<option value="">未選択</option>']
    for credential in credentials:
        selected = " selected" if str(credential["id"]) == selected_credential_profile_id else ""
        options.append(
            f'<option value="{credential["id"]}"{selected}>{escape(credential["profile_name"])}</option>'
        )
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    body = f"""
    <section class="page-head compact">
      <div>
        <a class="back-link" href="/accounts?platform={escape(selected_platform)}">← アカウント連携に戻る</a>
        <h1>新しいアカウントを連携</h1>
        <p>まずは手動登録で FredCore のアカウント管理を始められるようにしています。</p>
      </div>
    </section>
    <section class="card form-card">
      {error_html}
      <form method="post" action="/accounts/new">
        <label>プラットフォーム
          <select name="platform">
            {render_platform_options(selected_platform)}
          </select>
        </label>
        <label>アカウント名
          <input type="text" name="account_name" value="{escape(values.get('account_name', ''))}" required>
        </label>
        <label>アカウントID
          <input type="text" name="account_identifier" value="{escape(values.get('account_identifier', ''))}" required>
        </label>
        <label>タイムゾーン
          <input type="text" name="timezone_name" value="{escape(values.get('timezone_name', 'Asia/Tokyo'))}" required>
        </label>
        <label>認証プロフィール
          <select name="credential_profile_id">
            {''.join(options)}
          </select>
        </label>
        <label>操作担当者
          <input type="email" name="operator_email" value="{escape(values.get('operator_email', ''))}" required>
        </label>
        <label>親アカウント
          <input type="text" name="parent_account" value="{escape(values.get('parent_account', '-'))}">
        </label>
        <div class="form-actions">
          <a class="secondary-btn" href="/accounts?platform={escape(selected_platform)}">キャンセル</a>
          <button class="primary-btn" type="submit">連携を保存</button>
        </div>
      </form>
    </section>
    """
    return render_layout("新しいアカウントを連携", body, "/accounts")


def render_credential_form(active_platform: str, error: str = "") -> bytes:
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    body = f"""
    <section class="page-head compact">
      <div>
        <a class="back-link" href="/credentials?platform={escape(active_platform)}">← 認証情報一覧に戻る</a>
        <h1>新しい認証情報を追加</h1>
        <p>本番の OAuth 接続前でも、どの認証でどのアカウントが動くかを先に整理できます。</p>
      </div>
    </section>
    <section class="card form-card">
      {error_html}
      <form method="post" action="/credentials/new">
        <label>プラットフォーム
          <select name="platform">
            {render_platform_options(active_platform)}
          </select>
        </label>
        <label>認証プロフィール名
          <input type="text" name="profile_name" required>
        </label>
        <label>認証プロフィールID
          <input type="text" name="profile_identifier" required>
        </label>
        <label>作成者メール
          <input type="email" name="creator_email" value="" required>
        </label>
        <label>認証期限
          <input type="text" name="auth_expiry" placeholder="2026-05-31 12:00">
        </label>
        <div class="form-actions">
          <a class="secondary-btn" href="/credentials?platform={escape(active_platform)}">キャンセル</a>
          <button class="primary-btn" type="submit">認証情報を保存</button>
        </div>
      </form>
    </section>
    """
    return render_layout("新しい認証情報を追加", body, "/credentials")


def render_report_sheets_page(
    rows,
    *,
    notice: str = "",
    error: str = "",
    settings=None,
    default_month_key: str = "",
    current_user: Optional[dict] = None,
) -> bytes:
    header = """
    <section class="page-head">
      <div>
        <h1>月別スプレッドシート</h1>
        <p>毎月の広告消化キャンペーン一覧を出す Google スプレッドシート URL を管理します。</p>
      </div>
    </section>
    """
    table_rows = []
    for row in rows:
        table_rows.append(
            f"""
            <tr>
              <td>{escape(row["month_key"])}</td>
              <td>{escape(row["spreadsheet_title"])}</td>
              <td><a class="text-link" href="{escape(row["spreadsheet_url"])}" target="_blank" rel="noreferrer">スプレッドシートを開く</a></td>
              <td class="action-cell">
                <form method="post" action="/report-sheets/{row["id"]}/delete">
                  <button class="danger-link" type="submit">削除</button>
                </form>
              </td>
            </tr>
            """
        )

    body = f"""
    {header}
    {render_feedback(notice, error)}
    <section class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>対象月</th>
              <th>スプシ名</th>
              <th>URL</th>
              <th>アクション</th>
            </tr>
          </thead>
          <tbody>
            {''.join(table_rows) if table_rows else '<tr><td colspan="4" class="empty">まだ月別スプレッドシートは登録されていません。</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
    """
    return render_layout("月別スプレッドシート", body, "/report-sheets", current_user)


def render_report_sheet_form(
    *,
    month_key: str,
    spreadsheet_url: str = "",
    spreadsheet_title: str = "",
    status: str = "有効",
    notes: str = "",
    error: str = "",
) -> bytes:
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    selected_active = " selected" if status == "有効" else ""
    selected_paused = " selected" if status == "停止中" else ""
    body = f"""
    <section class="page-head compact">
      <div>
        <a class="back-link" href="/report-sheets">← 月別スプレッドシートに戻る</a>
        <h1>月別スプシを追加</h1>
        <p>月ごとの出力先 URL を先に登録しておくことで、日次同期の保存先を固定できます。</p>
      </div>
    </section>
    <section class="card form-card">
      {error_html}
      <form method="post" action="/report-sheets/new">
        <label>対象月
          <input type="month" name="month_key" value="{escape(month_key)}" required>
        </label>
        <label>ステータス
          <select name="status">
            <option value="有効"{selected_active}>有効</option>
            <option value="停止中"{selected_paused}>停止中</option>
          </select>
        </label>
        <label>スプレッドシートURL
          <input type="url" name="spreadsheet_url" value="{escape(spreadsheet_url)}" placeholder="https://docs.google.com/spreadsheets/d/..." required>
        </label>
        <label>スプレッドシート名
          <input type="text" name="spreadsheet_title" value="{escape(spreadsheet_title)}" placeholder="2026年4月 広告消化キャンペーン一覧" required>
        </label>
        <label style="grid-column: 1 / -1;">メモ
          <input type="text" name="notes" value="{escape(notes)}" placeholder="4月分の本番出力先">
        </label>
        <div class="form-actions">
          <a class="secondary-btn" href="/report-sheets">キャンセル</a>
          <button class="primary-btn" type="submit">保存</button>
        </div>
      </form>
    </section>
    """
    return render_layout("月別スプシを追加", body, "/report-sheets")


def render_sync_runs_page(rows, *, notice: str = "", error: str = "", current_user: Optional[dict] = None) -> bytes:
    header = """
    <section class="page-head">
      <div>
        <h1>同期履歴</h1>
        <p>手動実行と日次ジョブの結果を確認できます。失敗時はここでエラーメッセージを追えます。</p>
      </div>
    </section>
    """
    table_rows = []
    for row in rows:
        status_class = "green" if row["status"] == "成功" else "warn" if row["status"] == "実行中" else "red"
        summary = (
            f"対象アカウント {row['account_count']}件 / 行 {row['row_count']}件 / 更新 {row['updated_count']}件 / 追加 {row['appended_count']}件"
            if row["status"] == "成功"
            else row["error_message"] or "-"
        )
        sheet_html = (
            f'<a class="text-link" href="{escape(row["spreadsheet_url"])}" target="_blank" rel="noreferrer">{escape(row["spreadsheet_title"] or "月次スプシを開く")}</a>'
            if row["spreadsheet_url"]
            else "-"
        )
        table_rows.append(
            f"""
            <tr>
              <td>{escape(row["started_at"])}</td>
              <td>{escape(row["trigger_source"])}</td>
              <td>{escape(row["report_date"])}</td>
              <td>{escape(row["month_key"])}</td>
              <td><span class="badge {status_class}">{escape(row["status"])}</span></td>
              <td>{sheet_html}</td>
              <td>{escape(summary)}</td>
            </tr>
            """
        )
    body = f"""
    {header}
    {render_feedback(notice, error)}
    <section class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>開始日時</th>
              <th>実行元</th>
              <th>対象日</th>
              <th>対象月</th>
              <th>ステータス</th>
              <th>出力先スプシ</th>
              <th>結果</th>
            </tr>
          </thead>
          <tbody>
            {''.join(table_rows) if table_rows else '<tr><td colspan="7" class="empty">まだ同期履歴はありません。</td></tr>'}
          </tbody>
        </table>
      </div>
    </section>
    """
    return render_layout("同期履歴", body, "/sync-runs", current_user)


def render_placeholder_page(title: str, description: str, current_path: str) -> bytes:
    body = f"""
    <section class="page-head">
      <div>
        <h1>{escape(title)}</h1>
        <p>{escape(description)}</p>
      </div>
    </section>
    <section class="card placeholder-card">
      <p>この画面は次のフェーズで実装します。まずはアカウント連携と認証情報一覧から固めています。</p>
    </section>
    """
    return render_layout(title, body, current_path)


def render_platform_options(active_platform: str) -> str:
    options = []
    for platform in SUPPORTED_PLATFORMS:
        selected = " selected" if platform == active_platform else ""
        options.append(
            f'<option value="{platform}"{selected}>{PLATFORM_LABELS[platform]}</option>'
        )
    return "".join(options)


def render_keyed_options(options, selected_value: str) -> str:
    rendered = []
    for value, label in options:
        selected = " selected" if value == selected_value else ""
        rendered.append(
            f'<option value="{escape(value)}"{selected}>{escape(label)}</option>'
        )
    return "".join(rendered)
