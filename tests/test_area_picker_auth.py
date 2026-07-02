import importlib
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT / "Scripts" / "app" / "area_picker" / "frontend"


class TestAreaPickerAuth(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_env = {
            "VC_AREA_PICKER_AUTH_DB": os.environ.get("VC_AREA_PICKER_AUTH_DB"),
            "VC_AREA_PICKER_INVITE_CODES": os.environ.get("VC_AREA_PICKER_INVITE_CODES"),
        }
        os.environ["VC_AREA_PICKER_AUTH_DB"] = str(Path(self._tmp.name) / "auth.db")
        os.environ["VC_AREA_PICKER_INVITE_CODES"] = "TEST-CODE"
        import app.area_picker.auth as auth

        self.auth = importlib.reload(auth)

    def tearDown(self):
        if self.auth._conn is not None:
            self.auth._conn.close()
            self.auth._conn = None
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_dev_login_creates_session_without_email_password_or_invite(self):
        result = self.auth.dev_login()

        self.assertTrue(result["ok"])
        self.assertEqual(result["email"], self.auth.DEV_LOGIN_EMAIL)
        self.assertIn("token", result)
        self.assertEqual(
            self.auth.user_for_token(result["token"]),
            {"id": 1, "email": self.auth.DEV_LOGIN_EMAIL},
        )


class TestAreaPickerDevLoginPage(unittest.TestCase):
    def test_login_page_uses_single_dev_login_button(self):
        html = (FRONTEND_ROOT / "login.html").read_text(encoding="utf-8")
        script = (FRONTEND_ROOT / "login.js").read_text(encoding="utf-8")

        self.assertIn("login-submit-login", html)
        self.assertNotIn("login-email-input", html)
        self.assertNotIn("login-password-input", html)
        self.assertNotIn("register-invite-input", html)
        self.assertNotIn("data-login-tab", html)
        self.assertIn("dev_login: true", script)


if __name__ == "__main__":
    unittest.main()
