import unittest

from app.config import normalize_account_id


class NormalizeAccountIdTest(unittest.TestCase):
    def test_removes_act_prefix(self):
        self.assertEqual(normalize_account_id("act_1234567890"), "1234567890")

    def test_keeps_plain_numeric_id(self):
        self.assertEqual(normalize_account_id("1234567890"), "1234567890")


if __name__ == "__main__":
    unittest.main()
