import http.server
import json
import pathlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from backend import scanner


VALID_AUTH_PASSWORD = "aaAA11!!" + "x" * 17


class TestApiAuthSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_secrets_path = scanner.SECRETS_PATH
        cls._old_config_path = scanner.CONFIG_PATH
        cls._tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls._tmp.name)
        cls._secrets_path = root / ".secrets"
        cls._config_path = root / "config.json"
        scanner.SECRETS_PATH = str(cls._secrets_path)
        scanner.CONFIG_PATH = str(cls._config_path)
        cls._write_auth_hash("test-password")

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
        scanner.SECRETS_PATH = cls._old_secrets_path
        scanner.CONFIG_PATH = cls._old_config_path
        cls._tmp.cleanup()

    def setUp(self):
        scanner._valid_sessions.clear()
        scanner._auth_attempts.clear()
        self._write_auth_hash("test-password")

    @classmethod
    def _write_auth_hash(cls, password: str):
        cls._secrets_path.write_text(json.dumps({
            "auth_password_hash": scanner._auth_hash_password(password),
        }), encoding="utf-8")

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
        for path in ("/api/config", "/api/scan/log", "/api/scan/status", "/api/settings/score"):
            status, _, _ = self._request(path)
            self.assertEqual(status, 401, path)

    def test_protected_post_endpoint_requires_auth(self):
        status, _, _ = self._request("/api/scan/start", method="POST", payload={"mode": "quick"})
        self.assertEqual(status, 401)

    def test_protected_put_endpoint_requires_auth(self):
        status, _, _ = self._request("/api/settings/score", method="PUT", payload={"score": {}})
        self.assertEqual(status, 401)

    def test_auth_validate_requires_session_cookie(self):
        status, _, _ = self._request("/api/auth/validate")
        self.assertEqual(status, 401)

    def test_auth_endpoint_reports_authentication_state_without_401(self):
        status, body, _ = self._request("/api/auth")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["required"])
        self.assertFalse(payload["authenticated"])

        status, _, headers = self._request("/api/auth", method="POST", payload={"password": "test-password"})
        self.assertEqual(status, 200)
        cookie_pair = (headers.get("Set-Cookie") or "").split(";", 1)[0]
        self.assertTrue(cookie_pair.startswith("mml_session="))

        status, body, _ = self._request("/api/auth", headers={"Cookie": cookie_pair})
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["authenticated"])

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

    def test_legacy_plaintext_secret_migrates_to_hash_after_successful_login(self):
        self._secrets_path.write_text("legacy-password", encoding="utf-8")

        status, body, _ = self._request("/api/auth", method="POST", payload={"password": "legacy-password"})
        self.assertEqual(status, 200)
        self.assertIn('"ok": true', body.lower())

        stored = json.loads(self._secrets_path.read_text(encoding="utf-8"))
        self.assertIn("auth_password_hash", stored)
        self.assertNotIn("legacy-password", self._secrets_path.read_text(encoding="utf-8"))
        self.assertTrue(scanner._auth_check_password_hash(stored["auth_password_hash"], "legacy-password"))

    def test_legacy_dot_secret_file_migrates_to_hash_after_successful_login(self):
        self._secrets_path.unlink(missing_ok=True)
        legacy_path = self._secrets_path.with_name(".secret")
        legacy_path.write_text("legacy-dot-secret", encoding="utf-8")

        status, body, _ = self._request("/api/auth", method="POST", payload={"password": "legacy-dot-secret"})
        self.assertEqual(status, 200)
        self.assertIn('"ok": true', body.lower())

        self.assertFalse(legacy_path.exists())
        stored = json.loads(self._secrets_path.read_text(encoding="utf-8"))
        self.assertTrue(scanner._auth_check_password_hash(stored["auth_password_hash"], "legacy-dot-secret"))

    def test_config_api_never_exposes_auth_hash(self):
        status, _, headers = self._request("/api/auth", method="POST", payload={"password": "test-password"})
        cookie_pair = (headers.get("Set-Cookie") or "").split(";", 1)[0]

        status, body, _ = self._request("/api/config", headers={"Cookie": cookie_pair})
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload.get("auth"), {"enabled": True})
        self.assertNotIn("auth_password_hash", body)
        self.assertNotIn("test-password", body)

    def test_config_api_writes_only_hash_for_auth_password(self):
        status, _, headers = self._request("/api/auth", method="POST", payload={"password": "test-password"})
        cookie_pair = (headers.get("Set-Cookie") or "").split(";", 1)[0]

        status, body, headers = self._request(
            "/api/config",
            method="POST",
            headers={"Cookie": cookie_pair},
            payload={"auth": {"enabled": True, "password": VALID_AUTH_PASSWORD, "password_confirm": VALID_AUTH_PASSWORD}},
        )
        self.assertEqual(status, 200, body)
        self.assertIn("mml_session=", headers.get("Set-Cookie") or "")

        raw = self._secrets_path.read_text(encoding="utf-8")
        self.assertNotIn(VALID_AUTH_PASSWORD, raw)
        stored = json.loads(raw)
        self.assertTrue(scanner._auth_check_password_hash(stored["auth_password_hash"], VALID_AUTH_PASSWORD))

    def test_config_api_rejects_invalid_auth_password(self):
        status, _, headers = self._request("/api/auth", method="POST", payload={"password": "test-password"})
        cookie_pair = (headers.get("Set-Cookie") or "").split(";", 1)[0]

        invalid_cases = [
            "aaAA11!!" + "x" * 16, # too short
            "AABB11!!" + "Z" * 17, # no lowercase
            "aabb11!!" + "x" * 17, # no uppercase
            "aaAA!!!!" + "x" * 17, # no digits
            "aaAA1122" + "x" * 17, # no special chars
        ]
        for password in invalid_cases:
            status, body, _ = self._request(
                "/api/config",
                method="POST",
                headers={"Cookie": cookie_pair},
                payload={"auth": {"enabled": True, "password": password, "password_confirm": password}},
            )
            self.assertEqual(status, 400, body)
            self.assertIn("INVALID_AUTH_CONFIG", body)

    def test_config_api_rejects_auth_confirmation_mismatch(self):
        status, _, headers = self._request("/api/auth", method="POST", payload={"password": "test-password"})
        cookie_pair = (headers.get("Set-Cookie") or "").split(";", 1)[0]

        status, body, _ = self._request(
            "/api/config",
            method="POST",
            headers={"Cookie": cookie_pair},
            payload={"auth": {"enabled": True, "password": VALID_AUTH_PASSWORD, "password_confirm": VALID_AUTH_PASSWORD + "x"}},
        )
        self.assertEqual(status, 400, body)
        self.assertIn("INVALID_AUTH_CONFIG", body)

    def test_backend_auth_password_validation_rules(self):
        ok, details = scanner.validate_auth_password(VALID_AUTH_PASSWORD, VALID_AUTH_PASSWORD)
        self.assertTrue(ok)
        self.assertTrue(all(details["rules"].values()))
        self.assertTrue(details["confirmation_matches"])

        for password, failed_rule in [
            ("aaAA11!!" + "x" * 16, "length"),
            ("AABB11!!" + "Z" * 17, "lowercase"),
            ("aabb11!!" + "x" * 17, "uppercase"),
            ("aaAA!!!!" + "x" * 17, "digits"),
            ("aaAA1122" + "x" * 17, "special"),
        ]:
            ok, details = scanner.validate_auth_password(password, password)
            self.assertFalse(ok)
            self.assertFalse(details["rules"][failed_rule])


class TestRecommendationsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_config_path = scanner.CONFIG_PATH
        cls._old_recommendations_output_path = scanner.RECOMMENDATIONS_OUTPUT_PATH
        cls._old_secrets_path = scanner.SECRETS_PATH
        cls._tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls._tmp.name)
        cls._config_path = root / "config.json"
        cls._recommendations_path = root / "recommendations.json"
        cls._secrets_path = root / ".secrets"

        scanner.CONFIG_PATH = str(cls._config_path)
        scanner.RECOMMENDATIONS_OUTPUT_PATH = str(cls._recommendations_path)
        scanner.SECRETS_PATH = str(cls._secrets_path)

        cls._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), scanner._ScanHandler)
        cls._port = cls._server.server_address[1]
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=2)

        scanner.CONFIG_PATH = cls._old_config_path
        scanner.RECOMMENDATIONS_OUTPUT_PATH = cls._old_recommendations_output_path
        scanner.SECRETS_PATH = cls._old_secrets_path
        cls._tmp.cleanup()

    def setUp(self):
        self._write_config(recommendations_enabled=True)
        if self._recommendations_path.exists():
            self._recommendations_path.unlink()

    @classmethod
    def _url(cls, path: str) -> str:
        return f"http://127.0.0.1:{cls._port}{path}"

    @classmethod
    def _request(cls, path: str):
        req = urllib.request.Request(cls._url(path), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def _write_config(self, *, recommendations_enabled: bool):
        self._config_path.write_text(json.dumps({
            "score": {"enabled": True},
            "recommendations": {"enabled": recommendations_enabled},
        }), encoding="utf-8")

    def test_get_recommendations_returns_empty_state_when_file_is_absent(self):
        status, payload = self._request("/api/recommendations")
        self.assertEqual(status, 200)
        self.assertIs(payload["enabled"], True)
        self.assertEqual(payload["items"], [])
        self.assertIsNone(payload["generated_at"])

    def test_get_recommendations_returns_generated_items(self):
        self._recommendations_path.write_text(json.dumps({
            "generated_at": "2026-04-24T18:00:00Z",
            "version": 1,
            "items": [{"id": "rec:movie:test:low_score", "media_ref": {"id": "movie:test", "type": "movie"}}],
        }), encoding="utf-8")

        status, payload = self._request("/api/recommendations")
        self.assertEqual(status, 200)
        self.assertIs(payload["enabled"], True)
        self.assertEqual(payload["generated_at"], "2026-04-24T18:00:00Z")
        self.assertEqual(len(payload["items"]), 1)

    def test_get_recommendations_returns_disabled_state_without_404(self):
        self._write_config(recommendations_enabled=False)
        status, payload = self._request("/api/recommendations")
        self.assertEqual(status, 200)
        self.assertIs(payload["enabled"], False)
        self.assertEqual(payload["items"], [])
