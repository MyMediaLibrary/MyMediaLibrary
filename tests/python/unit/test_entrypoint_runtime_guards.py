import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"


class EntrypointRuntimeGuardsTest(unittest.TestCase):
    def test_tz_fallback_is_exported_before_scanner_processes_start(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        tz_idx = source.index('export TZ')
        scan_server_idx = source.index('python3 /app/scanner.py --serve &')
        initial_scan_idx = source.index('python3 /app/scanner.py')
        self.assertLess(tz_idx, scan_server_idx)
        self.assertLess(tz_idx, initial_scan_idx)

    def test_entrypoint_does_not_redirect_scanner_stdout_to_log_path(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertNotIn('>> "${LOG_PATH', source)
        self.assertNotIn('>>"${LOG_PATH', source)


if __name__ == "__main__":
    unittest.main()
