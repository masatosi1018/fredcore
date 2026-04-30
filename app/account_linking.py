from __future__ import annotations


ACCOUNT_LINK_FLOW = {
    "google": {
        "label": "Google広告",
        "short_label": "Google",
        "description": "Google検索、YouTube、Displayネットワークの広告アカウントを連携します。",
        "features": [
            "検索広告",
            "ディスプレイ広告",
            "YouTube広告",
            "ショッピング広告",
        ],
        "auth_title": "Google広告との連携",
        "auth_description": "保存済みの Google 認証プロフィールを選んで、広告アカウント取得に進みます。",
        "auth_points": [
            "Google アカウントの認証情報一覧と連動します",
            "広告アカウントへのアクセス権のみを前提にします",
            "認証プロフィールはあとから差し替えできます",
        ],
        "notice_title": "Google連携について",
        "notice_body": [
            "認証プロフィール一覧に保存済みの Google アカウントを使って連携します。",
            "OAuth の実装を入れるまでは、ここでは保存済みプロフィールの選択を入口にします。",
        ],
        "login_label": "Googleで続行",
    },
    "meta": {
        "label": "Meta広告",
        "short_label": "Meta",
        "description": "Facebook、Instagram、Messenger の広告アカウントを連携します。",
        "features": [
            "Facebook広告",
            "Instagram広告",
            "Messenger広告",
            "Audience Network",
        ],
        "auth_title": "Meta広告との連携",
        "auth_description": "保存済みの Meta 認証プロフィールを選んで、広告アカウント取得に進みます。",
        "auth_points": [
            "安全な OAuth 認証を前提にした導線です",
            "パスワードはこのサービスに保存しません",
            "必要最小限の権限だけを扱う想定です",
        ],
        "notice_title": "Meta連携に関する重要なお知らせ",
        "notice_body": [
            "Meta の仕様により、連携直後に追加確認が求められる場合があります。",
            "本実装ではまず認証プロフィール選択と広告アカウント連携の流れを先に固めています。",
        ],
        "login_label": "Facebookで続行",
    },
    "tiktok": {
        "label": "TikTok広告",
        "short_label": "TikTok",
        "description": "TikTok Ads Manager の広告アカウントを連携します。",
        "features": [
            "In-Feed広告",
            "Spark Ads",
            "動画広告",
            "リード獲得広告",
        ],
        "auth_title": "TikTok広告との連携",
        "auth_description": "保存済みの TikTok 認証プロフィールを選んで、広告アカウント取得に進みます。",
        "auth_points": [
            "認証プロフィール一覧の TikTok アカウントと連動します",
            "複数の広告アカウントをまとめて追加できます",
            "連携後の広告費取得先として使えます",
        ],
        "notice_title": "TikTok連携について",
        "notice_body": [
            "TikTok の認証情報も他媒体と同じ一覧で管理します。",
            "広告アカウントの実取得を入れる前に、UI と保存フローを先に完成させます。",
        ],
        "login_label": "TikTokで続行",
    },
}


DISCOVERABLE_ACCOUNTS = {
    "google": [
        {
            "account_name": "株式会社物販ONE08/fred",
            "account_identifier": "4696494872",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
        {
            "account_name": "アズール株式会社09/fred",
            "account_identifier": "1060984764",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
        {
            "account_name": "株式会社ミライラボラトリー05/fred",
            "account_identifier": "6659927996",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
        {
            "account_name": "株式会社LADDER03/fred",
            "account_identifier": "6276773654",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
        {
            "account_name": "アドネス株式会社08/fred",
            "account_identifier": "5049084174",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
        {
            "account_name": "株式会社TOEZ12/fred",
            "account_identifier": "9337704507",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
        {
            "account_name": "FRED Google Growth 01",
            "account_identifier": "2084451911",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
    ],
    "meta": [
        {
            "account_name": "CM_株式会社FRED_キャプの恋愛コンサル1",
            "account_identifier": "7213735899",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "Fred Holdings",
        },
        {
            "account_name": "Fred_2",
            "account_identifier": "5520616537",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "Fred Holdings",
        },
        {
            "account_name": "株式会社FRED/こはくの龍神鑑定_FRED_02",
            "account_identifier": "7775530207",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "Fred Holdings",
        },
        {
            "account_name": "CM_株式会社FRED_キャプの恋愛コンサル2",
            "account_identifier": "5933209186",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "Fred Holdings",
        },
        {
            "account_name": "株式会社FRED/こはくの龍神鑑定_FRED_01",
            "account_identifier": "6140101009",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "Fred Holdings",
        },
        {
            "account_name": "CM_株式会社FRED_さゆりママの鑑定2",
            "account_identifier": "4459119342",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "Fred Holdings",
        },
        {
            "account_name": "LEON",
            "account_identifier": "4459100021",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "Fred Holdings",
        },
        {
            "account_name": "fred_meta_main",
            "account_identifier": "act_120011223344",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "Fred Holdings",
        },
        {
            "account_name": "fred_meta_sub",
            "account_identifier": "act_120011223355",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "Fred Holdings",
        },
    ],
    "tiktok": [
        {
            "account_name": "fred_tiktok_growth",
            "account_identifier": "tt-77889911",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
        {
            "account_name": "Fred TikTok Lead Gen",
            "account_identifier": "tt-77889912",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
        {
            "account_name": "Fred TikTok Creative Lab",
            "account_identifier": "tt-77889913",
            "timezone_name": "Asia/Tokyo",
            "parent_account": "-",
        },
    ],
}


def list_discoverable_accounts(platform: str):
    return [dict(account) for account in DISCOVERABLE_ACCOUNTS.get(platform, [])]


def find_discoverable_accounts(platform: str, identifiers):
    lookup = {
        account["account_identifier"]: dict(account)
        for account in DISCOVERABLE_ACCOUNTS.get(platform, [])
    }
    matched = []
    for identifier in identifiers:
        account = lookup.get(identifier)
        if account is not None:
            matched.append(account)
    return matched
