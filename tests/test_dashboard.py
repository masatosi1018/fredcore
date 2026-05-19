import io
import tempfile
import unittest
from pathlib import Path

from app import dashboard
from app.admin_db import AdminRepository


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = AdminRepository(Path(self.temp_dir.name) / "fredcore.db")
        self.repository.initialize()
        self.repository.seed_if_empty()
        self.original_repository = dashboard.REPOSITORY
        self.original_start_credential_oauth_flow = dashboard.start_credential_oauth_flow
        self.original_complete_credential_oauth = dashboard.complete_credential_oauth
        self.original_fetch_linkable_accounts = dashboard.fetch_linkable_accounts
        dashboard.REPOSITORY = self.repository

    def tearDown(self):
        dashboard.REPOSITORY = self.original_repository
        dashboard.start_credential_oauth_flow = self.original_start_credential_oauth_flow
        dashboard.complete_credential_oauth = self.original_complete_credential_oauth
        dashboard.fetch_linkable_accounts = self.original_fetch_linkable_accounts
        self.temp_dir.cleanup()

    def request(self, path: str, *, method: str = "GET", query: str = "", body: str = ""):
        payload = body.encode("utf-8")
        environ = {
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": str(len(payload)),
            "wsgi.input": io.BytesIO(payload),
        }
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        chunks = dashboard.application(environ, start_response)
        captured["body"] = b"".join(chunks).decode("utf-8")
        return captured

    def test_accounts_page_renders_link_modal_and_hides_rules_nav(self):
        response = self.request("/accounts", query="platform=meta")
        self.assertEqual(response["status"], "200 OK")
        self.assertIn("広告アカウント連携", response["body"])
        self.assertIn("data-open-account-link-modal", response["body"])
        self.assertNotIn("自動運用ルール", response["body"])

    def test_credentials_page_renders_add_modal(self):
        response = self.request("/credentials", query="platform=google")
        self.assertEqual(response["status"], "200 OK")
        self.assertIn("認証情報を追加", response["body"])
        self.assertIn("data-open-credential-modal", response["body"])
        self.assertIn("Google OAuth", response["body"])

    def test_post_account_link_creates_multiple_accounts(self):
        credential_id = str(self.repository.list_credentials("meta")[0]["id"])
        dashboard.fetch_linkable_accounts = lambda **kwargs: {
            "credential_profile_name": "Meta OAuth User",
            "accounts": [
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
            ],
        }
        response = self.request(
            "/accounts/link",
            method="POST",
            body=(
                f"platform=meta&credential_profile_id={credential_id}"
                "&selected_account_ids=7213735899%2C5520616537"
            ),
        )
        self.assertEqual(response["status"], "303 See Other")
        self.assertIn("/accounts?platform=meta", response["headers"]["Location"])
        rows = self.repository.list_accounts("meta")
        identifiers = {row["account_identifier"] for row in rows}
        self.assertIn("7213735899", identifiers)
        self.assertIn("5520616537", identifiers)

    def test_meta_account_candidates_endpoint_returns_json(self):
        credential_id = str(
            self.repository.list_credentials("meta")[0]["id"]
        )
        dashboard.fetch_linkable_accounts = lambda **kwargs: {
            "credential_profile_name": "Meta OAuth User",
            "accounts": [
                {
                    "account_name": "Meta Account A",
                    "account_identifier": "9988776655",
                    "timezone_name": "Asia/Tokyo",
                    "parent_account": "Fred Holdings",
                }
            ],
        }
        response = self.request(
            "/api/account-candidates",
            query=f"platform=meta&credential_profile_id={credential_id}",
        )
        self.assertEqual(response["status"], "200 OK")
        self.assertIn('"ok": true', response["body"])
        self.assertIn("Meta Account A", response["body"])

    def test_meta_account_candidates_endpoint_requires_credential(self):
        response = self.request(
            "/api/account-candidates",
            query="platform=meta",
        )
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertIn("Meta の認証プロフィールを選択してください", response["body"])

    def test_health_endpoint_reports_backend(self):
        response = self.request("/api/health")
        self.assertEqual(response["status"], "200 OK")
        self.assertIn('"ok": true', response["body"])
        self.assertIn('"database_backend": "sqlite"', response["body"])

    def test_post_credential_create_saves_auth_type(self):
        response = self.request(
            "/credentials/new",
            method="POST",
            body=(
                "platform=google&auth_type=service_account"
                "&profile_name=Sheets+Service"
                "&profile_identifier=sheets-service%40project.iam.gserviceaccount.com"
                "&creator_email=test%40example.com"
                "&auth_expiry=&external_user_id=svc-123&token_expires_at="
            ),
        )
        self.assertEqual(response["status"], "303 See Other")
        rows = self.repository.list_credentials("google", "Sheets Service")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["auth_type"], "service_account")
        self.assertEqual(rows[0]["external_user_id"], "svc-123")

    def test_post_credential_oauth_redirects_to_provider(self):
        dashboard.start_credential_oauth_flow = lambda form: "https://accounts.example.test/oauth"
        response = self.request(
            "/credentials/new",
            method="POST",
            body=(
                "platform=google&auth_type=oauth"
                "&profile_name=&profile_identifier=&creator_email=test%40example.com"
            ),
        )
        self.assertEqual(response["status"], "303 See Other")
        self.assertEqual(response["headers"]["Location"], "https://accounts.example.test/oauth")

    def test_google_oauth_callback_redirects_with_notice(self):
        dashboard.complete_credential_oauth = lambda platform, state, code: "Google OAuth User"
        response = self.request(
            "/oauth/google/callback",
            query="state=state-123&code=auth-code-1",
        )
        self.assertEqual(response["status"], "303 See Other")
        self.assertIn("/credentials?platform=google", response["headers"]["Location"])
        self.assertIn("Google+OAuth+User", response["headers"]["Location"])

    def test_should_watch_path_ignores_virtualenv_and_watches_python(self):
        self.assertTrue(dashboard.should_watch_path(Path("app/dashboard.py")))
        self.assertFalse(dashboard.should_watch_path(Path(".venv/lib/site.py")))

    def test_detect_changed_paths_reports_modified_file(self):
        previous = {"a.py": 1, "b.css": 2}
        current = {"a.py": 3, "b.css": 2}
        self.assertEqual(dashboard.detect_changed_paths(previous, current), ["a.py"])


if __name__ == "__main__":
    unittest.main()
