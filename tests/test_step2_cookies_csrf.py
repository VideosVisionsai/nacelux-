"""Step 2 (ÉTAPE 2.5) — REAL verification of authentication cookie attributes
and the CSRF double-submit contract, by exercising the real ``auth.cookie_headers``
code path (not a mock). Full HTTP Set-Cookie round-trips on login require a real
Supabase project (REQUIRES CONFIGURATION).
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import auth  # noqa: E402

SAMPLE = {"access_token": "ACCESS.JWT.PAYLOAD", "refresh_token": "REFRESH.TOKEN", "expires_in": 3600}


def _find(headers, prefix):
    return [h for h in headers if h.startswith(prefix)]


class CookieAttributeTests(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get("AUTH_COOKIE_SECURE")

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("AUTH_COOKIE_SECURE", None)
        else:
            os.environ["AUTH_COOKIE_SECURE"] = self._orig

    def test_session_cookies_are_httponly_secure_samesite_lax_in_production(self):
        os.environ["AUTH_COOKIE_SECURE"] = "true"
        headers = auth.cookie_headers(SAMPLE)
        for cookie in ("nacelux_access=", "nacelux_refresh="):
            line = _find(headers, cookie)
            self.assertEqual(len(line), 1, f"{cookie} cookie missing")
            self.assertIn("HttpOnly", line[0])
            self.assertIn("Secure", line[0])
            self.assertIn("SameSite=Lax", line[0])

    def test_csrf_cookie_is_js_readable_and_samesite_lax(self):
        os.environ["AUTH_COOKIE_SECURE"] = "true"
        headers = auth.cookie_headers(SAMPLE)
        csrf = _find(headers, "nacelux_csrf=")
        self.assertEqual(len(csrf), 1)
        # The CSRF token must be readable by JS (to echo it in X-CSRF-Token),
        # so it must NOT be HttpOnly; it still carries SameSite=Lax.
        self.assertIn("SameSite=Lax", csrf[0])
        self.assertNotIn("HttpOnly", csrf[0])

    def test_access_and_refresh_cookies_carry_distinct_max_ages(self):
        os.environ["AUTH_COOKIE_SECURE"] = "true"
        headers = auth.cookie_headers(SAMPLE)
        access = _find(headers, "nacelux_access=")[0]
        refresh = _find(headers, "nacelux_refresh=")[0]
        self.assertIn("Max-Age=3600", access)
        self.assertIn("Max-Age=2592000", refresh)  # 30 days

    def test_dev_mode_omits_secure_flag_until_configured(self):
        os.environ["AUTH_COOKIE_SECURE"] = "false"
        headers = auth.cookie_headers(SAMPLE)
        access = _find(headers, "nacelux_access=")[0]
        self.assertIn("HttpOnly", access)
        self.assertIn("SameSite=Lax", access)
        self.assertNotIn("Secure", access)  # Secure only when AUTH_COOKIE_SECURE=true

    def test_clear_cookies_expire_immediately(self):
        headers = auth.cookie_headers(clear=True)
        for cookie in ("nacelux_access=", "nacelux_refresh=", "nacelux_csrf="):
            line = _find(headers, cookie)
            self.assertEqual(len(line), 1, f"{cookie} clear header missing")
            self.assertIn("Max-Age=0", line[0])


class CsrfTokenContractTests(unittest.TestCase):
    def test_csrf_token_is_random_and_non_constant(self):
        a = auth.cookie_headers(SAMPLE)
        b = auth.cookie_headers(SAMPLE)
        ta = _find(a, "nacelux_csrf=")[0].split("nacelux_csrf=")[1].split(";")[0]
        tb = _find(b, "nacelux_csrf=")[0].split("nacelux_csrf=")[1].split(";")[0]
        self.assertTrue(ta and tb)
        self.assertNotEqual(ta, tb)  # freshly generated per session

    def test_refreshed_session_reissues_cookie_headers(self):
        refreshed = {"access_token": "NEW.ACCESS", "refresh_token": "NEW.REFRESH", "expires_in": 3600}
        headers = auth.cookie_headers(refreshed)
        self.assertIn(_find(headers, "nacelux_access=")[0].split("nacelux_access=")[1].split(";")[0],
                      "NEW.ACCESS")


if __name__ == "__main__":
    unittest.main()
