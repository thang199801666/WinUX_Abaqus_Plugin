"""New file/folder creation must select, reveal and inline-rename the item."""
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.controllers.file_commands import FileCommandController
from WinUx.ui.components.explorer_rename import ExplorerRenameMixin
from WinUx.ui.components.file_panel import FilePanel


def rename_view(items, *, visible_return=False):
    """Partial ExplorerListView bound to the rename mixin for unit checks."""
    view = SimpleNamespace(
        items=items,
        body_window="body",
        ROW_HEIGHT=24.0,
        _sync_qt_selection_from_fields=Mock(
            return_value=SimpleNamespace(selected=set(), current=None)),
        select_indices=Mock(),
        begin_inline_rename=Mock(return_value=True),
        _scroll_row_into_view=Mock(return_value=visible_return),
    )
    return view


class BeginRenameForCreatedItemTests(unittest.TestCase):
    def test_visible_new_item_selects_and_opens_editor_now(self):
        view = rename_view([
            SimpleNamespace(name="a", path=PurePosixPath("/folder/a")),
            SimpleNamespace(name="new", path=PurePosixPath("/folder/new")),
        ])
        result = ExplorerRenameMixin.begin_rename_for_created_item(view, 0)
        self.assertTrue(result)
        view.select_indices.assert_called_once_with([0])
        view.begin_inline_rename.assert_called_once_with(0)

    def test_existing_focus_is_not_reselected(self):
        view = rename_view([
            SimpleNamespace(name="new", path=PurePosixPath("/folder/new")),
        ])
        view._sync_qt_selection_from_fields.return_value = SimpleNamespace(
            selected={0}, current=0)
        ExplorerRenameMixin.begin_rename_for_created_item(view, 0)
        view.select_indices.assert_not_called()
        view.begin_inline_rename.assert_called_once_with(0)

    def test_hidden_new_item_scrolls_and_defers_editor_one_frame(self):
        view = rename_view(
            [SimpleNamespace(name="new", path=PurePosixPath("/folder/new"))],
            visible_return=True)
        scheduled = Mock()
        with patch("WinUx.ui.components.explorer_rename.QGuiRuntime") as runtime:
            runtime.return_value.invokeNextFrame = scheduled
            result = ExplorerRenameMixin.begin_rename_for_created_item(view, 0)
        self.assertTrue(result)
        view._scroll_row_into_view.assert_called_once_with(0)
        view.begin_inline_rename.assert_not_called()
        scheduled.call_args.args[0]()
        view.begin_inline_rename.assert_called_once_with(0)

    def test_out_of_range_index_reports_false_without_side_effects(self):
        view = rename_view([])
        self.assertFalse(ExplorerRenameMixin.begin_rename_for_created_item(view, 3))
        view.select_indices.assert_not_called()
        view.begin_inline_rename.assert_not_called()
        self.assertFalse(ExplorerRenameMixin.begin_rename_for_created_item(view, None))


class FilePanelCreatedRenameQueueTests(unittest.TestCase):
    def make_panel(self, *, with_row=True):
        panel = object.__new__(FilePanel)
        panel.current_path = Path("folder")
        panel._pending_created_rename = None
        panel._rename_commit_callback = None
        panel._source_items = []
        panel.has_status = False
        created = SimpleNamespace(name="new", path=Path("folder/new"))
        items = [SimpleNamespace(name="new", path=Path("folder/new"),
                                 data={"path": Path("folder/new")}),
                 SimpleNamespace(name="other", path=Path("folder/other"),
                                 data={"path": Path("folder/other")})]
        if not with_row:
            items = items[1:]
        panel.listview = SimpleNamespace(
            items=items,
            select_indices=Mock(),
            begin_rename_for_created_item=Mock(return_value=True),
            begin_inline_rename=Mock(return_value=True))
        return panel

    def test_missing_row_is_queued_and_applied_after_display(self):
        panel = self.make_panel(with_row=False)
        commit = Mock()
        self.assertFalse(panel.focus_created_item(Path("folder/new"), commit))
        self.assertIsNotNone(panel._pending_created_rename)
        panel.listview.begin_rename_for_created_item.assert_not_called()
        panel.listview.select_indices.assert_not_called()

        # The refreshed listing (display) now contains the created row.
        panel.listview.items = [panel.listview.items[0],
                                SimpleNamespace(name="new", path=Path("folder/new"),
                                                data={"path": Path("folder/new")})]
        panel._consume_pending_created_rename()
        panel.listview.select_indices.assert_called_once_with([1])
        panel.listview.begin_rename_for_created_item.assert_called_once_with(1)
        self.assertIsNone(panel._pending_created_rename)
        self.assertIs(panel._rename_commit_callback, commit)
        # The queue is consumed exactly once.
        panel._consume_pending_created_rename()
        panel.listview.select_indices.assert_called_once()
        panel.listview.begin_rename_for_created_item.assert_called_once()

    def test_row_present_renames_immediately(self):
        panel = self.make_panel()
        commit = Mock()
        self.assertTrue(panel.focus_created_item(Path("folder/new"), commit))
        panel.listview.select_indices.assert_called_once_with([0])
        panel.listview.begin_rename_for_created_item.assert_called_once_with(0)
        self.assertIsNone(panel._pending_created_rename)
        self.assertIs(panel._rename_commit_callback, commit)

    def test_new_item_installs_commit_before_editor_can_accept_enter(self):
        panel = self.make_panel()
        commit = Mock(return_value=Path("folder/newfile.txt"))
        item = panel.listview.items[0]
        panel._rename_commit_callback = Mock(return_value=False)
        panel.listview.begin_rename_for_created_item.side_effect = (
            lambda row: panel._rename_commit(item, "newfile.txt"))
        self.assertTrue(panel.focus_created_item(Path("folder/new"), commit))
        commit.assert_called_once_with("newfile.txt")
        self.assertIsNone(panel._rename_commit_callback)

    def test_pending_queue_is_dropped_when_folder_changes(self):
        panel = self.make_panel(with_row=False)
        panel.focus_created_item(Path("folder/new"), Mock())
        panel.current_path = Path("other")
        panel._consume_pending_created_rename()
        self.assertIsNone(panel._pending_created_rename)
        panel.listview.begin_rename_for_created_item.assert_not_called()

    def test_windows_style_case_insensitive_row_matches_new_items(self):
        panel = self.make_panel()
        panel.current_path = Path("FOLDER")
        commit = Mock()
        self.assertTrue(panel.focus_created_item(Path("folder\\NEW"), commit))
        panel.listview.begin_rename_for_created_item.assert_called_once()


class CreatedItemCommitContractTests(unittest.TestCase):
    def test_local_controller_calls_focus_created_item_with_created_path(self):
        from tests.test_file_command_components import fixture

        app, panel, commands, workers, callbacks = fixture(remote=False)
        if panel is None:
            self.fail("fixture panel missing")
        panel.current_path = Path("folder")
        commands._begin_created_rename(panel, Path("folder/new"))
        panel.focus_created_item.assert_called_once()
        created, commit = panel.focus_created_item.call_args.args
        self.assertEqual(created, Path("folder/new"))
        self.assertTrue(callable(commit))


if __name__ == "__main__":
    unittest.main()
