import pathlib
import re
import unittest


class TestNginxAuthGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conf_path = pathlib.Path(__file__).resolve().parents[3] / "docker" / "nginx.conf"
        cls.conf = cls.conf_path.read_text(encoding="utf-8")

    def test_library_json_is_guarded_with_auth_request(self):
        block = re.search(r"location = /library\.json \{(?P<body>.*?)\n\s*\}", self.conf, flags=re.S)
        self.assertIsNotNone(block)
        body = block.group("body")
        self.assertIn("auth_request /api/auth/validate;", body)
        self.assertIn("error_page 401 = @auth_error;", body)

        auth_error = re.search(r"location @auth_error \{(?P<body>.*?)\n\s*\}", self.conf, flags=re.S)
        self.assertIsNotNone(auth_error)
        self.assertIn("return 401", auth_error.group("body"))

    def test_docs_html_is_guarded_with_auth_request_and_redirect(self):
        block = re.search(r"location = /docs\.html \{(?P<body>.*?)\n\s*\}", self.conf, flags=re.S)
        self.assertIsNotNone(block)
        body = block.group("body")
        self.assertIn("auth_request /api/auth/validate;", body)
        self.assertIn("error_page 401 = @auth_redirect;", body)

        redirect = re.search(r"location @auth_redirect \{(?P<body>.*?)\n\s*\}", self.conf, flags=re.S)
        self.assertIsNotNone(redirect)
        self.assertIn("return 302", redirect.group("body"))

    def test_recommendations_api_is_proxied_to_scanner(self):
        block = re.search(r"location /api/recommendations \{(?P<body>.*?)\n\s*\}", self.conf, flags=re.S)
        self.assertIsNotNone(block)
        body = block.group("body")
        self.assertIn("proxy_pass         http://127.0.0.1:8095;", body)

    def test_posters_use_fixed_library_root(self):
        block = re.search(r"location /posters/ \{(?P<body>.*?)\n\s*\}", self.conf, flags=re.S)
        self.assertIsNotNone(block)
        body = block.group("body")
        self.assertIn("root /library;", body)
        self.assertNotIn("LIBRARY_PATH", self.conf)
        self.assertNotIn("${", self.conf)
