import http.server
import json
import pathlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from backend import scanner


class TestScoreSettingsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls._tmp_path = pathlib.Path(cls._tmp.name)

        cls.config_path = cls._tmp_path / "config.json"
        cls.output_path = cls._tmp_path / "library.json"
        cls.score_defaults_path = pathlib.Path(__file__).resolve().parents[3] / "backend" / "score_defaults.json"
        cls.scan_lock_path = cls._tmp_path / ".scan.lock"

        cls.config_path.write_text(json.dumps({
            "system": {
                "enable_score": True,
                "scan_cron": "0 3 * * *",
                "log_level": "INFO",
                "inventory_enabled": False,
            },
            "folders": [],
            "enable_movies": True,
            "enable_series": True,
            "jellyseerr": {"enabled": False, "url": ""},
            "providers_visible": [],
            "ui": {"synopsis_on_hover": False},
            "custom_flag": "keep-me",
        }), encoding="utf-8")

        cls.output_path.write_text(json.dumps({
            "items": [
                {
                    "title": "Film Test",
                    "type": "movie",
                    "resolution": "1080p",
                    "codec": "H.265",
                    "audio_codec": "DTS",
                    "audio_languages_simple": "MULTI",
                    "size_b": int(5 * (1024 ** 3)),
                }
            ]
        }), encoding="utf-8")

        cls._patches = [
            patch.object(scanner, "CONFIG_PATH", str(cls.config_path)),
            patch.object(scanner, "OUTPUT_PATH", str(cls.output_path)),
            patch.object(scanner, "SCORE_DEFAULTS_PATH", str(cls.score_defaults_path)),
            patch.object(scanner, "SCAN_LOCK_PATH", str(cls.scan_lock_path)),
        ]
        for p in cls._patches:
            p.start()

        cls._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), scanner._ScanHandler)
        cls._port = cls._server.server_address[1]
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=2)
        for p in reversed(cls._patches):
            p.stop()
        cls._tmp.cleanup()

    @classmethod
    def _url(cls, path: str) -> str:
        return f"http://127.0.0.1:{cls._port}{path}"

    @classmethod
    def _request(cls, path: str, method: str = "GET", payload=None):
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(cls._url(path), data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    def test_get_score_settings_returns_effective_payload(self):
        status, payload = self._request("/api/settings/score")
        self.assertEqual(status, 200)
        self.assertIn("defaults", payload)
        self.assertIn("effective", payload)
        self.assertIn("ui_schema", payload)
        self.assertIn("status", payload)
        self.assertEqual(payload["status"]["weights_total"], 100)
        self.assertTrue(payload["status"]["weights_valid"])

    def test_put_score_settings_recomputes_scores_only(self):
        status, get_payload = self._request("/api/settings/score")
        self.assertEqual(status, 200)
        effective = get_payload["effective"]
        effective["weights"]["video"] = 48
        effective["weights"]["audio"] = 22

        put_status, put_payload = self._request("/api/settings/score", method="PUT", payload={"score": effective})
        self.assertEqual(put_status, 200)
        self.assertTrue(put_payload["ok"])
        self.assertEqual(put_payload["status"]["mode"], "score_only")
        self.assertEqual(put_payload["status"]["recalculated_items"], 1)

        data = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertIn("quality", data["items"][0])
        self.assertIn("score", data["items"][0]["quality"])

    def test_put_invalid_weights_returns_structured_error(self):
        status, get_payload = self._request("/api/settings/score")
        self.assertEqual(status, 200)
        invalid = get_payload["effective"]
        invalid["weights"]["video"] = 10

        put_status, put_payload = self._request("/api/settings/score", method="PUT", payload={"score": invalid})
        self.assertEqual(put_status, 400)
        self.assertFalse(put_payload["ok"])
        self.assertEqual(put_payload["error"]["code"], "INVALID_SCORE_CONFIG")

    def test_reset_score_settings_only_touches_score_block(self):
        status, _ = self._request("/api/settings/score/reset", method="POST", payload={})
        self.assertEqual(status, 200)

        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn("score", cfg)
        self.assertEqual(cfg.get("custom_flag"), "keep-me")
