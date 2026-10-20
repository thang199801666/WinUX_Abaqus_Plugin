"""Server refresh routing keeps navigation and live editing semantics intact."""
import ast
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tests.test_navigation_controller import app_fixture
from WinUx.ui.components.file_panel import FilePanel
from WinUx.ui.components.explorer_item_model import stable_item_identity


def display_method():
    path = Path(__file__).resolve().parents[1] / "WinUx/view.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "WinUXView")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
                  and node.name == "display_server_directory")
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"), namespace)
    return namespace[method.name]


class ServerRefreshTests(unittest.TestCase):
    def setUp(self):
        self.path = PurePosixPath("/work")
        self.panel = SimpleNamespace(current_path=self.path, status_prefix="host",
                                     history=[self.path], history_index=0, has_status=True,
                                     refresh_directory=Mock(), display=Mock(), _update_item_status=Mock())
        self.view = SimpleNamespace(right=self.panel)
        self.display = display_method()

    def test_same_directory_uses_incremental_refresh_and_restores_status(self):
        self.display(self.view, self.path, ["new-file"], "host", record_history=False)
        self.panel.refresh_directory.assert_called_once_with(self.path, ["new-file"])
        self.panel.display.assert_not_called()
        self.panel._update_item_status.assert_called_once()
        self.assertEqual(self.panel.history, [self.path])

    def test_navigation_keeps_normal_display_and_history_flag(self):
        self.display(self.view, PurePosixPath("/other"), [], "host", record_history=False)
        self.panel.display.assert_called_once_with(PurePosixPath("/other"), [], record_history=False)
        self.panel.refresh_directory.assert_not_called()

    def test_reconnect_resets_even_if_host_and_path_match(self):
        self.display(self.view, self.path, [], "host", reset_history=True)
        self.panel.refresh_directory.assert_not_called()
        self.panel.display.assert_called_once()
        self.assertEqual(self.panel.history, [])

    def test_other_host_does_not_reuse_previous_listing(self):
        self.display(self.view, self.path, [], "new-host")
        self.panel.refresh_directory.assert_not_called()
        self.panel.display.assert_called_once()

    def test_same_folder_refresh_does_not_steal_focus(self):
        app, navigation, _, _ = app_fixture()
        app.view.right.current_path = self.path
        navigation.server_loaded(app.view.right, self.path, [], False, 0)
        app.view.right.focus.assert_not_called()

    def test_completed_listing_waits_for_rename_and_rejects_stale_retry(self):
        app, navigation, _, callbacks = app_fixture()
        panel = app.view.right
        panel.current_path = self.path
        panel.listview = SimpleNamespace(_rename_active=True)
        navigation._deliver_server_result(panel, self.path, [], False, 0, 0)
        app.view.display_server_directory.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        callback, args = callbacks.pop()
        panel.listview._rename_active = False
        app._connection_generation += 1
        callback(*args)
        app.view.display_server_directory.assert_not_called()

    def test_completed_listing_applies_after_drag_finishes(self):
        app, navigation, _, callbacks = app_fixture()
        panel = app.view.right
        panel.current_path = self.path
        panel.listview = SimpleNamespace(_item_drag_active=True)
        navigation._deliver_server_result(panel, self.path, [], False, 0, 0)
        callback, args = callbacks.pop()
        panel.listview._item_drag_active = False
        callback(*args)
        app.view.display_server_directory.assert_called_once()

    def test_linux_case_sensitive_paths_keep_distinct_row_identities(self):
        upper = SimpleNamespace(path="/work/A.inp", data={"path": self.path / "A.inp"})
        lower = SimpleNamespace(path="/work/a.inp", data={"path": self.path / "a.inp"})
        self.assertNotEqual(stable_item_identity(upper), stable_item_identity(lower))
        self.assertNotEqual(FilePanel._path_identity(upper.data["path"]),
                            FilePanel._path_identity(lower.data["path"]))


if __name__ == "__main__":
    unittest.main()
