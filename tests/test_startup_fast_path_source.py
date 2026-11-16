import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StartupFastPathSourceTests(unittest.TestCase):
    def test_launcher_does_not_import_full_updater_on_menu_launch_path(self):
        source = (ROOT / "winux_runtime" / "launcher.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "from winux_runtime.update.updater import DEFAULT_NETWORK_PROJECT_DIR",
            source,
        )
        self.assertIn(
            "from winux_runtime.update.constants import DEFAULT_NETWORK_PROJECT_DIR",
            source,
        )

    def test_run_winux_uses_version_bound_startup_update_cache(self):
        source = (ROOT / "run_winux.py").read_text(encoding="utf-8")
        self.assertIn("cached_startup_status", source)
        self.assertIn("record_startup_status", source)
        self.assertIn("startup update cache hit", source)

    def test_first_visible_frame_is_recorded_in_end_to_end_timing(self):
        source = (ROOT / "WinUx" / "ui" / "behaviors" / "window" / "lifecycle.py").read_text(encoding="utf-8")
        self.assertIn('note_startup_milestone("first visible frame rendered")', source)


if __name__ == "__main__":
    unittest.main()
