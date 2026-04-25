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

    def test_storage_migration_runs_before_scanner_processes_start(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        migration_idx = source.index('python3 -m backend.storage_migration || exit 1')
        scan_server_idx = source.index('python3 /app/scanner.py --serve &')
        initial_scan_idx = source.index('python3 /app/scanner.py')
        self.assertLess(migration_idx, scan_server_idx)
        self.assertLess(migration_idx, initial_scan_idx)

    def test_entrypoint_does_not_redirect_scanner_stdout_to_log_path(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertNotIn('>> "${LOG_PATH', source)
        self.assertNotIn('>>"${LOG_PATH', source)

    def test_entrypoint_uses_python_scheduler_not_external_crond(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn('python3 /app/scanner.py --serve &', source)
        self.assertIn('wait "$SCANSERVER_PID"', source)
        self.assertNotIn('crond -f', source)
        self.assertNotIn('scan_cron.sh', source)
        self.assertNotIn('Cron schedule:', source)
        self.assertNotIn('CRON_FILE="/etc/crontabs/root"', source)
        self.assertNotIn('CRON_FILE="/etc/cron.d/mymedialibrary"', source)


if __name__ == "__main__":
    unittest.main()
