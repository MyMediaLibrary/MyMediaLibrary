import http.server
import json
import os
import threading
import unittest
import urllib.error
import urllib.request

from backend import scanner


class TestApiAuthSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_password = os.environ.get("APP_PASSWORD")
        os.environ["APP_PASSWORD"] = "test-password"

        scanner._valid_sessions.clear()
        scanner._auth_attempts.clear()

        scanner._srv_state.update(
            status="idle",
            mode=None,
            started_at=None,
            ended_at=None,
            log=[],
        )

        cls._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), scanner._ScanHandler)
        cls._port = cls._server.server_address[1]
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=2)

        scanner._valid_sessions.clear()
        scanner._auth_attempts.clear()

        if cls._old_password is None:
            os.environ.pop("APP_PASSWORD", None)
        else:
            os.environ["APP_PASSWORD"] = cls._old_password

    def setUp(self):
        scanner._valid_sessions.clear()
        scanner._auth_attempts.clear()

    @classmethod
    def _url(cls, path: str) -> str:
        return f"http://127.0.0.1:{cls._port}{path}"

    @classmethod
    def _request(cls, path: str, method: str = "GET", payload=None, headers=None):
        req_headers = dict(headers or {})
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(cls._url(path), data=body, method=method, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8"), resp.headers
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode("utf-8"), err.headers

    def test_protected_get_endpoints_require_auth(self):
        for path in ("/api/config", "/api/scan/log", "/api/scan/status"):
            status, _, _ = self._request(path)
            self.assertEqual(status, 401, path)

    def test_protected_post_endpoint_requires_auth(self):
        status, _, _ = self._request("/api/scan/start", method="POST", payload={"mode": "quick"})
        self.assertEqual(status, 401)

    def test_auth_validate_requires_session_cookie(self):
        status, _, _ = self._request("/api/auth/validate")
        self.assertEqual(status, 401)

    def test_auth_rate_limit_returns_429(self):
        for _ in range(scanner._AUTH_MAX_ATTEMPTS):
            status, _, _ = self._request("/api/auth", method="POST", payload={"password": "wrong"})
            self.assertEqual(status, 200)

        status, body, _ = self._request("/api/auth", method="POST", payload={"password": "wrong"})
        self.assertEqual(status, 429)
        self.assertIn("too many attempts", body)

    def test_logout_invalidates_session_and_expires_cookie(self):
        status, body, headers = self._request("/api/auth", method="POST", payload={"password": "test-password"})
        self.assertEqual(status, 200)
        self.assertIn('"ok": true', body.lower())

        set_cookie = headers.get("Set-Cookie") or ""
        cookie_pair = set_cookie.split(";", 1)[0]
        self.assertTrue(cookie_pair.startswith("mml_session="))

        status, _, _ = self._request("/api/auth/validate", headers={"Cookie": cookie_pair})
        self.assertEqual(status, 200)

        status, _, headers = self._request("/api/logout", method="POST", headers={"Cookie": cookie_pair})
        self.assertEqual(status, 200)
        expired_cookie = headers.get("Set-Cookie") or ""
        self.assertIn("mml_session=", expired_cookie)
        self.assertIn("Max-Age=0", expired_cookie)

        status, _, _ = self._request("/api/auth/validate", headers={"Cookie": cookie_pair})
        self.assertEqual(status, 401)
