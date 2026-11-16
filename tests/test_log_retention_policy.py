import logging
import os
from pathlib import Path
import tempfile
import unittest

from winux_runtime.logging_policy import (
    normal_log_level_name,
    trim_log_tail,
    verbose_startup_logging,
)


class LogRetentionPolicyTests(unittest.TestCase):
    def test_trim_log_tail_bounds_append_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.log"
            path.write_bytes((b"line-xxxxxxxxxxxxxxxx\n" * 2000))
            self.assertGreater(path.stat().st_size, 4096)
            self.assertTrue(trim_log_tail(str(path), max_bytes=4096, keep_bytes=1024))
            data = path.read_bytes()
            self.assertLessEqual(len(data), 1200)
            self.assertIn(b"keeping recent entries", data.splitlines()[0])

    def test_normal_level_is_warning_by_default(self):
        env = dict(os.environ)
        old = os.environ.pop("WINUX_LOG_LEVEL", None)
        try:
            self.assertEqual(normal_log_level_name(), "WARNING")
        finally:
            if old is not None:
                os.environ["WINUX_LOG_LEVEL"] = old

    def test_verbose_startup_is_opt_in(self):
        self.assertFalse(verbose_startup_logging({}))
        self.assertTrue(verbose_startup_logging({"WINUX_VERBOSE_STARTUP_LOG": "1"}))

    def test_crash_logger_defaults_are_bounded(self):
        import WinUx.diagnostics.crash_logging as crash
        self.assertLessEqual(crash.MAX_LOG_BYTES, 512 * 1024)
        self.assertLessEqual(crash.LOG_BACKUP_COUNT, 2)
        self.assertLessEqual(crash.NATIVE_LOG_RETENTION, 3)


if __name__ == "__main__":
    unittest.main()
