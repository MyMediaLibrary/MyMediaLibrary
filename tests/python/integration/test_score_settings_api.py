import http.server
import copy
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
            "system": {"scan_cron": "0 3 * * *", "log_level": "INFO", "inventory_enabled": False},
            "score": {"enabled": True},
            "folders": [],
            "enable_movies": True,
            "enable_series": True,
            "seerr": {"enabled": False, "url": ""},
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
        self.assertIs(payload.get("enabled"), True)
        self.assertIn("defaults", payload)
        self.assertIn("effective", payload)
        self.assertIn("ui_schema", payload)
        self.assertIn("status", payload)
        self.assertNotIn("schema_version", payload)
        self.assertNotIn("schema_version", payload["defaults"])
        self.assertNotIn("schema_version", payload["effective"])
        self.assertNotIn("penalties", payload["defaults"])
        self.assertNotIn("penalties", payload["effective"])
        self.assertEqual(payload["status"]["weights_total"], 100)
        self.assertTrue(payload["status"]["weights_valid"])
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn("score", cfg)
        self.assertIn("score_configuration", cfg)
        self.assertNotIn("enabled", cfg.get("score_configuration", {}))

    def test_put_score_settings_recomputes_scores_only(self):
        status, get_payload = self._request("/api/settings/score")
        self.assertEqual(status, 200)
        baseline_cfg = copy.deepcopy(get_payload["effective"])
        baseline_status, baseline_payload = self._request(
            "/api/settings/score",
            method="PUT",
            payload={"score": baseline_cfg},
        )
        self.assertEqual(baseline_status, 200)
        self.assertTrue(baseline_payload["ok"])
        baseline_data = json.loads(self.output_path.read_text(encoding="utf-8"))
        score_before = baseline_data["items"][0]["quality"]["score"]

        weighted_cfg = copy.deepcopy(get_payload["effective"])
        weighted_cfg["weights"]["video"] = 10
        weighted_cfg["weights"]["audio"] = 10
        weighted_cfg["weights"]["languages"] = 10
        weighted_cfg["weights"]["size"] = 70

        put_status, put_payload = self._request("/api/settings/score", method="PUT", payload={"score": weighted_cfg})
        self.assertEqual(put_status, 200)
        self.assertTrue(put_payload["ok"])
        self.assertEqual(put_payload["status"]["mode"], "score_only")
        self.assertEqual(put_payload["status"]["recalculated_items"], 1)

        data = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertIn("quality", data["items"][0])
        self.assertIn("score", data["items"][0]["quality"])
        score_after = data["items"][0]["quality"]["score"]
        self.assertNotEqual(score_before, score_after)

    def test_put_invalid_weights_returns_structured_error(self):
        status, get_payload = self._request("/api/settings/score")
        self.assertEqual(status, 200)
        invalid = get_payload["effective"]
        invalid["weights"]["video"] = 10

        put_status, put_payload = self._request("/api/settings/score", method="PUT", payload={"score": invalid})
        self.assertEqual(put_status, 400)
        self.assertFalse(put_payload["ok"])
        self.assertEqual(put_payload["error"]["code"], "INVALID_SCORE_CONFIG")

    def test_put_legacy_penalties_payload_is_ignored(self):
        status, get_payload = self._request("/api/settings/score")
        self.assertEqual(status, 200)
        mutated = get_payload["effective"]
        mutated["penalties"] = {"max_total": 20, "rules": {"size_incoherent": -5}}

        put_status, put_payload = self._request("/api/settings/score", method="PUT", payload={"score": mutated})
        self.assertEqual(put_status, 200)
        self.assertTrue(put_payload["ok"])
        self.assertNotIn("penalties", put_payload["effective"])

        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertNotIn("penalties", cfg.get("score_configuration", {}))

    def test_reset_score_settings_only_touches_score_block(self):
        before_cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        enabled_before = before_cfg.get("score", {}).get("enabled")
        status, _ = self._request("/api/settings/score/reset", method="POST", payload={})
        self.assertEqual(status, 200)

        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertIn("score", cfg)
        self.assertIn("score_configuration", cfg)
        self.assertEqual(cfg["score"]["enabled"], enabled_before)
        self.assertEqual(cfg.get("custom_flag"), "keep-me")

    def test_put_when_score_disabled_does_not_recompute(self):
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["score"]["enabled"] = False
        self.config_path.write_text(json.dumps(cfg), encoding="utf-8")
        status, get_payload = self._request("/api/settings/score")
        self.assertEqual(status, 200)

        put_status, put_payload = self._request(
            "/api/settings/score",
            method="PUT",
            payload={"score": get_payload["effective"]},
        )
        self.assertEqual(put_status, 200)
        self.assertEqual(put_payload["status"]["mode"], "config_only")
        self.assertEqual(put_payload["status"]["recalculated_items"], 0)

    def test_legacy_score_block_migrates_to_score_configuration(self):
        legacy_cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        legacy_cfg["score"] = {
            "enabled": True,
            "weights": {"video": 48, "audio": 22, "languages": 15, "size": 15},
            "audio": {"codec": {"aac": 7, "default": 8}},
        }
        legacy_cfg.pop("score_configuration", None)
        self.config_path.write_text(json.dumps(legacy_cfg), encoding="utf-8")

        status, payload = self._request("/api/settings/score")
        self.assertEqual(status, 200)
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(cfg["score"], {"enabled": True})
        self.assertIn("score_configuration", cfg)
        self.assertEqual(cfg["score_configuration"]["weights"]["video"], 48)
        self.assertEqual(payload["effective"]["weights"]["audio"], 22)
