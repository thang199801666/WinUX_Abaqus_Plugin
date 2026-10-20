from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from WinUx.controllers.explorer_transfer_interaction import ExplorerTransferInteractionMixin
from WinUx.controllers.transfer import TransferController
from WinUx.ui.components.explorer_file_operations import ExplorerFileOperationsMixin


class _InteractionController(ExplorerTransferInteractionMixin):
    pass


def _panel(panel_id, current_path):
    return SimpleNamespace(
        panel_id=panel_id,
        current_path=str(current_path),
        clear_external_drop_highlight=Mock(),
        set_external_drop_highlight_at=Mock(),
        drag_transfer_paths=Mock(return_value=[]),
        selected_transfer_paths=Mock(return_value=[]),
        status=SimpleNamespace(set=Mock()),
    )


def test_same_folder_internal_drop_is_silent_and_never_queued(tmp_path):
    controller = _InteractionController()
    panel = _panel("local", tmp_path)
    source = tmp_path / "a.inp"
    source.write_text("data", encoding="utf-8")
    panel.selected_transfer_paths.return_value = [str(source)]

    controller.view = SimpleNamespace(panels=[panel], after=Mock())
    controller._drag_target_panel = None
    controller._drag_target_destination = None
    controller._drag_target_point = None
    controller._drop_target = Mock(return_value=(panel, str(tmp_path), (20, 30)))
    controller._drop_is_valid = Mock(return_value=False)
    controller._process_queued_drop = Mock()

    controller.drop(panel, 20, 30, False)

    controller._drop_is_valid.assert_called_once()
    controller.view.after.assert_not_called()
    controller._process_queued_drop.assert_not_called()
    panel.status.set.assert_not_called()


def test_same_folder_invalid_drop_is_silent_in_transfer_layer(tmp_path):
    app = SimpleNamespace(
        model=SimpleNamespace(normalize=lambda value: Path(value).resolve()),
        server=SimpleNamespace(connected=True),
        view=SimpleNamespace(),
    )
    transfer = TransferController(app)
    panel = _panel("local", tmp_path)
    source = tmp_path / "model.odb"
    source.write_bytes(b"odb")
    transfer.start_drop_transfer = Mock()

    transfer.process_queued_drop(
        panel, panel, str(tmp_path), False, [str(source)])

    panel.status.set.assert_not_called()
    transfer.start_drop_transfer.assert_not_called()


class _ClipboardOps(ExplorerFileOperationsMixin):
    def __init__(self, directory, selected):
        self.current_path = str(directory)
        self._selected_items = list(selected)
        self._clipboard_paths = []
        self._clipboard_mode = None
        self.items = []
        self.selected = set()
        self._current_index = None
        self.last_clicked_index = None
        self.on_move_error = None
        self.reload_path()

    def get_selected(self):
        return list(self._selected_items)

    def reload_path(self, preserve_selection=False):
        root = Path(self.current_path)
        self.items = [
            SimpleNamespace(path=str(path), is_dir=path.is_dir())
            for path in sorted(root.iterdir(), key=lambda p: p.name)
        ]

    def _sync_qt_selection_from_fields(self):
        return None

    def _update_selection_draws(self):
        return None

    def _update_status_bar(self):
        return None


def test_explicit_copy_paste_still_clones_file_and_folder_in_same_directory(tmp_path):
    file_path = tmp_path / "result.inp"
    file_path.write_text("inp", encoding="utf-8")
    folder_path = tmp_path / "Case"
    folder_path.mkdir()
    (folder_path / "job.txt").write_text("job", encoding="utf-8")

    selected = [
        SimpleNamespace(path=str(file_path), is_dir=False),
        SimpleNamespace(path=str(folder_path), is_dir=True),
    ]
    ops = _ClipboardOps(tmp_path, selected)

    ops.copy_selected()
    created = {Path(path).name for path in ops.paste(str(tmp_path))}

    assert "result (2).inp" in created
    assert "Case (2)" in created
    assert (tmp_path / "result (2).inp").read_text(encoding="utf-8") == "inp"
    assert (tmp_path / "Case (2)" / "job.txt").read_text(encoding="utf-8") == "job"
