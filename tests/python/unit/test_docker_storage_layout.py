import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]


class DockerStorageLayoutGuardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        cls.dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        cls.dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
        cls.entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
        cls.nginx = (ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.docs_fr = (ROOT / "docs" / "fr.md").read_text(encoding="utf-8")
        cls.docs_en = (ROOT / "docs" / "en.md").read_text(encoding="utf-8")

    def test_compose_uses_data_and_fixed_library_volume(self):
        self.assertIn("./data:/data", self.compose)
        self.assertNotIn("./conf:/conf", self.compose)
        self.assertRegex(self.compose, r":/library:ro\b")
        self.assertNotIn("LIBRARY_PATH", self.compose)
        self.assertNotRegex(self.compose, r":/tmp\b|:/tmp:")

    def test_dockerfile_embeds_conf_defaults_without_user_config_or_secret(self):
        self.assertIn("/app/defaults/conf/config.json", self.dockerfile)
        self.assertIn("/app/defaults/conf/providers_mapping.json", self.dockerfile)
        self.assertIn("/app/defaults/conf/providers_logo.json", self.dockerfile)
        self.assertIn("/app/defaults/conf/recommendations_rules.json", self.dockerfile)
        self.assertIn("ffmpeg", self.dockerfile)
        self.assertRegex(self.dockerfile, r"apk add --no-cache .*sqlite")
        self.assertIn("COPY backend/ /app/backend/", self.dockerfile)
        self.assertIn("COPY backend/scanner.py /app/scanner.py", self.dockerfile)
        self.assertIn('VOLUME ["/data"]', self.dockerfile)
        self.assertNotIn("/app/.secrets", self.dockerfile)
        self.assertNotIn("/data/config.json", self.dockerfile)

    def test_docker_context_does_not_exclude_backend_sqlite_runtime(self):
        self.assertIn("**/__pycache__/", self.dockerignore)
        self.assertIn("**/*.pyc", self.dockerignore)
        self.assertNotRegex(self.dockerignore, r"(?m)^backend/?$")
        self.assertNotIn("backend/db.py", self.dockerignore)
        self.assertNotIn("backend/repositories", self.dockerignore)

    def test_entrypoint_and_nginx_do_not_depend_on_library_path_env(self):
        combined = self.entrypoint + "\n" + self.nginx
        self.assertNotIn("LIBRARY_PATH", combined)
        self.assertNotIn("envsubst", combined)
        self.assertNotIn("${LIBRARY_PATH}", combined)
        self.assertIn("root /library;", self.nginx)
        self.assertIn("python3 -m backend.storage_migration || exit 1", self.entrypoint)

    def test_docs_show_new_compose_layout_without_tmp_mount_or_library_env(self):
        for name, source in {
            "README.md": self.readme,
            "docs/fr.md": self.docs_fr,
            "docs/en.md": self.docs_en,
        }.items():
            self.assertIn("./data:/data", source, name)
            self.assertNotIn("./conf:/conf", source, name)
            self.assertRegex(source, r":/library:ro\b", name)
            self.assertNotIn("LIBRARY_PATH", source, name)
            self.assertNotRegex(source, r":/tmp\b|:/tmp:", name)

    def test_docs_describe_storage_migration_to_data_secrets(self):
        for source in (self.readme, self.docs_fr, self.docs_en):
            self.assertIn("/data/.secrets", source)
            self.assertIn("/conf/.secrets", source)
            self.assertNotIn("config.json, providers, rules, .secrets", source)
        self.assertRegex(self.docs_en, re.compile(r"/conf/\.secrets.*migrated.*?/data/\.secrets", re.I | re.S))
        self.assertRegex(self.docs_fr, re.compile(r"/conf/\.secrets.*migré.*?/data/\.secrets", re.I | re.S))

    def test_nginx_blocks_runtime_storage_and_dotfiles(self):
        self.assertIn("location ~ /\\.", self.nginx)
        self.assertRegex(self.nginx, r"location ~ \^/\(data\|conf\)")


if __name__ == "__main__":
    unittest.main()
