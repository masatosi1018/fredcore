import unittest
from unittest.mock import patch

from app.meta_sync import merged_integration_settings


class MetaSyncTest(unittest.TestCase):
    def test_merged_integration_settings_keeps_defaults(self):
        merged = merged_integration_settings({"meta_access_token": "abc"})
        self.assertEqual(merged["meta_access_token"], "abc")
        self.assertEqual(merged["google_sheet_name"], "Meta Daily Spend")

    def test_merged_integration_settings_prefers_environment_values(self):
        with patch.dict(
            "os.environ",
            {
                "META_APP_ID": "env-app-id",
                "FREDCORE_APP_BASE_URL": "https://fredcore.vercel.app",
            },
            clear=False,
        ):
            merged = merged_integration_settings(
                {
                    "meta_app_id": "",
                    "app_base_url": "http://127.0.0.1:8000",
                }
            )

        self.assertEqual(merged["meta_app_id"], "env-app-id")
        self.assertEqual(merged["app_base_url"], "https://fredcore.vercel.app")


if __name__ == "__main__":
    unittest.main()
