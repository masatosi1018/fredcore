# FredCore 広告運用基盤 UI

Adasi のスクリーンショットを土台にしつつ、FRED 向けの広告運用基盤 `FredCore` として、まずは `アカウント連携` と `認証情報一覧` を管理できるローカル Web UI を実装しています。

この段階でできること:

- `アカウント連携` 一覧を媒体タブつきで表示
- `認証情報一覧` を媒体タブつきで表示
- `新しいアカウントを連携` から3ステップのモーダルで広告アカウントを追加
- 認証情報一覧に保存した Google / Meta / TikTok の認証プロフィールをアカウント連携に利用
- `新しい認証情報を追加` から3ステップのモーダルで認証プロフィールを追加
- Google / Meta の OAuth 認証プロフィールを保存
- Meta OAuth 認証プロフィールから広告アカウント候補を取得して連携
- 認証情報の `再認証` と、不要な行の `削除`
- `設定` 画面で Meta / Google Sheets 接続情報を保存
- 登録済み Meta アカウントの指定日数値を Google スプレッドシートへ手動転記
- SQLite に保存してローカルで状態を保持
- スクリーンショットに近いサイドバー型UI

まだ未完了のもの:

- 認証プロフィール単位での日次自動同期
- Google / TikTok の広告アカウント候補の API 取得
- OAuth 認証プロフィールをそのまま本番同期へ使う一本化

## 1. 起動方法

Python 3.8 以上で動きます。

```bash
python3 -m app.dashboard
```

`app/`, `static/`, `config/`, `tests/` 配下と `README.md` / `requirements.txt` / `.env.example` を監視しているので、開発中はファイル更新時にローカルサーバーが自動で再起動します。

Meta API と Google スプレッドシート転記まで使う場合は、あわせて依存ライブラリを入れてください。

```bash
pip install -r requirements.txt
```

起動後:

```text
http://127.0.0.1:8000
```

初回起動時に `data/fredcore.db` を作成し、スクリーンショットに寄せたサンプルデータを投入します。

### Vercel について

Vercel にデプロイする場合、Python の WSGI エントリポイントとしてルートの `server.py` を使います。

Vercel の Flask/Python ドキュメントでは、トップレベルの `server.py` / `index.py` / `app.py` などにある `app` を自動検出する形が案内されています。このリポジトリは `server.py` に合わせています。

ただし、このプロジェクトは今 `SQLite` を前提にしているため、Vercel 上では永続ディスクを使えません。現状のままでは `FREDCORE_DATABASE_PATH` 未指定時に `/tmp/fredcore.db` を使うため、データはインスタンス再起動やスケール時に消える前提です。

つまり現段階の Vercel デプロイは:

- 画面表示や UI 確認には使える
- 永続的な認証情報保存や OAuth state 保存には本番向きではない

本番運用するなら、将来的に外部DBへ切り替える必要があります。

Vercel で最低限そろえる値:

- `FREDCORE_DATABASE_PATH=/tmp/fredcore.db` 省略可
- `VERCEL=1` 自動付与
- `FREDCORE_APP_BASE_URL=https://fredcore.vercel.app`

よく使う Vercel Environment Variables:

- `FREDCORE_APP_BASE_URL`
- `META_APP_ID`
- `META_APP_SECRET`
- `META_ACCESS_TOKEN`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_SERVICE_ACCOUNT_FILE` または将来的な外部シークレット管理

デプロイ手順の最短ルート:

1. Vercel で GitHub の `masatosi1018/fredcore` を Import
2. Root Directory はそのまま
3. Python Version は `3.12`
4. Environment Variables に `FREDCORE_APP_BASE_URL=https://<本番ドメイン>` を設定
5. 必要に応じて `META_APP_ID` / `META_APP_SECRET` なども設定
6. Deploy 後、Meta 側の OAuth リダイレクト URI に `https://<本番ドメイン>/oauth/meta/callback` を登録

## 2. 画面

### アカウント連携

- 媒体タブ: `Meta / Google / TikTok`
- 検索
- アカウント一覧
- `新しいアカウントを連携` モーダル
- ステップ: `プラットフォーム選択 / 認証 / アカウント選択`

### 認証情報一覧

- 媒体タブ: `Meta / Google / TikTok`
- 検索
- 認証情報一覧
- `新しい認証情報を追加` モーダル
- ステップ: `プラットフォーム / 認証方式 / プロフィール情報`
- `再認証`
- `削除`

### 設定

- アプリのベースURL
- Google OAuth クライアントID / シークレット
- Meta App ID / Secret
- Meta アクセストークン
- Meta Graph API バージョン
- Google サービスアカウント JSON パス
- Google スプレッドシートID
- Google シート名
- レポート基準タイムゾーン

## 3. Meta App のセットアップ

`Meta` の OAuth 連携を使うには、`Meta for Developers` で FREDCore 用のアプリを1つ作成して、設定画面に `Meta App ID` / `Meta App Secret` を入れる必要があります。

おすすめの進め方:

1. `Meta for Developers` で FREDCore 専用アプリを新規作成する
2. アプリタイプは `Business` 系を選ぶ
3. `Facebook Login for Business` を前提に OAuth の設定を開く
4. リダイレクトURLに `http://127.0.0.1:8000/oauth/meta/callback` を追加する
5. 本番URLがある場合は、その `/oauth/meta/callback` も追加する
6. `App ID` と `App Secret` を FREDCore の `設定` に保存する
7. Meta 認証を行う担当者が、対象の Business Manager / 広告アカウントにアクセス権を持っていることを確認する

今の前提:

- Meta 認証プロフィールの追加には `Meta App ID / Secret` が必要です
- `新しいアカウントを連携` の Meta 候補取得は、その OAuth 認証プロフィールのアクセストークンを使います
- 現在の `指定日の数値をスプシへ転記` は、まだ `設定` 画面の `Meta アクセストークン` を使っています

つまり今の段階では、`Meta App` はアカウント連携のために必要で、`Meta アクセストークン` は日次同期のためにまだ別で必要です。将来的にはこの2つを認証プロフィール中心に寄せていく想定です。

### Meta 数値転記

1. `設定` で Meta と Google Sheets の接続情報を保存
2. `アカウント連携` の `Meta` タブを開く
3. 対象日を選んで `指定日の数値をスプシへ転記` を押す

登録済みの Meta アカウントIDを使って、指定日の `spend` をスプレッドシートへ upsert します。

## 4. 保存データ

SQLite を使っています。

- DB ファイル: `data/fredcore.db`
- アカウント: `linked_accounts`
- 認証情報: `credential_profiles`
- 同期設定: `integration_settings`

## 5. テスト

```bash
python3 -m unittest discover -s tests
```

## 6. 既存の Meta 広告費連携CLI

以前追加した Meta 広告費をスプレッドシートへ転記する CLI も残しています。

```bash
python3 -m app.main --dry-run
```

将来的にはこの CLI と今回の管理画面をつなげて、

- 認証プロフィール
- 連携アカウント
- 日次広告費取得
- スプレッドシート反映

を一つの UI から扱える形に広げられます。
