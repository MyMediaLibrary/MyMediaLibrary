import pathlib
import sys
import unittest
import logging

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

import scanner  # noqa: E402


class ScannerLoggingConfigTests(unittest.TestCase):
    def test_set_global_log_level_updates_root_and_handlers(self):
        handler = logging.StreamHandler()
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            scanner._set_global_log_level("DEBUG")
            self.assertEqual(root.level, logging.DEBUG)
            self.assertEqual(handler.level, logging.DEBUG)
        finally:
            root.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
