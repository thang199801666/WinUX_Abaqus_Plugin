from pathlib import Path
import tempfile
import unittest

from WinUx.preferences.navigation import NavigationPreferences
from WinUx.preferences.sites import SitePreferences


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "WinUx" / "view.py"
CONTROLLER = ROOT / "WinUx" / "controller.py"
TRANSFER = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"
SERVER_PATH = ROOT / "WinUx" / "dialogs" / "server_path_form.py"
DIAGNOSTICS = ROOT / "WinUx" / "dialogs" / "diagnostics_form.py"
PROGRESS = ROOT / "WinUx" / "dialogs" / "progress_form.py"
BOOKMARKS = ROOT / "WinUx" / "dialogs" / "bookmarks_form.py"
SITES = ROOT / "WinUx" / "dialogs" / "site_manager_form.py"
SYNC = ROOT / "WinUx" / "dialogs" / "sync_preview_form.py"


class BookmarkPreferenceTests(unittest.TestCase):
    def test_local_and_server_bookmarks_are_scoped(self):
        with tempfile.TemporaryDirectory() as root:
            prefs = NavigationPreferences(root=root)
            prefs.add_bookmark("local", r"C:\\Work", label="Work")
            prefs.add_bookmark(
                "server", "/scratch/project", label="Project",
                host="cluster", username="thang")
            self.assertEqual(prefs.load_bookmarks("local")[0]["label"], "Work")
            self.assertEqual(
                prefs.load_bookmarks("server", host="cluster", username="thang")[0]["path"],
                "/scratch/project")
            self.assertEqual(
                prefs.load_bookmarks("server", host="other", username="thang"), [])

    def test_bookmark_upsert_rename_and_remove(self):
        with tempfile.TemporaryDirectory() as root:
            prefs = NavigationPreferences(root=root)
            prefs.add_bookmark("local", "/tmp/a", label="A")
            prefs.add_bookmark("local", "/tmp/a", label="A2")
            self.assertEqual(len(prefs.load_bookmarks("local")), 1)
            prefs.rename_bookmark("local", "/tmp/a", "Renamed")
            self.assertEqual(prefs.load_bookmarks("local")[0]["label"], "Renamed")
            prefs.remove_bookmark("local", "/tmp/a")
            self.assertEqual(prefs.load_bookmarks("local"), [])


class SitePreferenceTests(unittest.TestCase):
    def test_sites_store_non_secret_connection_profiles(self):
        with tempfile.TemporaryDirectory() as root:
            prefs = SitePreferences(root=root)
            saved = prefs.save_site({
                "name": "CAE Cluster",
                "host": "server01",
                "port": 22,
                "username": "user",
                "remote_path": "/scratch/user",
                "password": "must-not-be-written",
            })
            self.assertTrue(saved["id"])
            loaded = prefs.load()
            self.assertEqual(loaded[0]["remote_path"], "/scratch/user")
            self.assertNotIn("password", loaded[0])
            self.assertNotIn("must-not-be-written", prefs.path.read_text(encoding="utf-8"))
            prefs.delete(saved["id"])
            self.assertEqual(prefs.load(), [])


class Phase3SourceRegressionTests(unittest.TestCase):
    def test_view_exposes_site_bookmark_and_sync_commands(self):
        source = VIEW.read_text(encoding="utf-8")
        self.assertIn('label="Bookmarks"', source)
        self.assertIn('"Site Manager..."', source)
        self.assertIn('"Synchronize Preview..."', source)
        self.assertIn("def show_bookmarks", source)
        self.assertIn("def show_site_manager", source)
        self.assertIn("def show_sync_preview", source)

    def test_sync_preview_uses_current_directory_diff_and_existing_transfer_pipeline(self):
        source = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("def _build_sync_rows", source)
        source += (ROOT / "WinUx" / "controllers" / "sync_preview.py").read_text(encoding="utf-8")
        self.assertIn('"Missing on server"', source)
        self.assertIn('"Missing locally"', source)
        self.assertIn('"Local is newer"', source)
        self.assertIn('"Server is newer"', source)
        self.assertIn("self.app._process_queued_drop(", source)

    def test_transfer_center_has_global_queue_controls(self):
        source = TRANSFER.read_text(encoding="utf-8")
        self.assertIn('"Clear Finished"', source)
        self.assertIn('"Cancel All"', source)
        self.assertIn("def request_clear_finished", source)
        self.assertIn("def request_cancel_all", source)
        self.assertIn("QtDialog", source.split("class TransferCenterDialog", 1)[1].split(":", 1)[0])

    def test_server_path_chooser_is_qt_style_and_bounded(self):
        source = SERVER_PATH.read_text(encoding="utf-8")
        self.assertIn("class ServerPathDialog(QtDialog)", source)
        self.assertIn("task_submitter", source)
        self.assertIn('key="server-path-search:{}".format(id(self))', source)
        self.assertIn("replace=True", source)
        self.assertIn("self.view.after", source)
        self.assertNotIn("tk.Toplevel", source)

    def test_diagnostics_uses_qt_style_dialog(self):
        source = DIAGNOSTICS.read_text(encoding="utf-8")
        self.assertIn("class DiagnosticsDialog(QtDialog)", source)
        self.assertIn("self.button_box", source)
        self.assertIn('("Save Report", self.save', source)
        self.assertNotIn("tk.Toplevel", source)

    def test_progress_handle_uses_qt_style_dialog(self):
        source = PROGRESS.read_text(encoding="utf-8")
        self.assertIn("class ProgressDialog(QtDialog)", source)
        self.assertIn("QProgressBar", source)
        self.assertIn('self.post_latest("progress"', source)
        wrapper = (ROOT / "WinUx" / "widgets" / "controls.py").read_text(encoding="utf-8")
        self.assertIn("backend.add_progress_bar", wrapper)
        self.assertIn("self.button_box", source)
        self.assertNotIn("tk.Toplevel", source)

    def test_phase3_dialogs_share_qt_dialog_framework(self):
        for path in (BOOKMARKS, SITES, SYNC):
            source = path.read_text(encoding="utf-8")
            self.assertIn("QtDialog", source)
            self.assertIn("self.button_box", source)
            self.assertNotIn("tk.Toplevel", source)


if __name__ == "__main__":
    unittest.main()
