"""Real pane/row geometry with deterministic drag-release routing, no SSH I/O."""
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.widgets import QRetainedItem
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.controllers.explorer_transfer_interaction import ExplorerTransferInteractionMixin
from WinUx.controllers.transfer import TransferController
from WinUx.models.items import FileItem
from WinUx.view import WinUXView


class DragApp(ExplorerTransferInteractionMixin):
    pass


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        def pump(count=12):
            for _ in range(count):
                view.update()
                time.sleep(.01)
        try:
            view._gui_runtime.show()
            view.left.display(Path(profile), [])
            view.right.display(PurePosixPath('/work'), [
                FileItem('a.inp', PurePosixPath('/work/a.inp'), False, 42, 100),
                FileItem('child', PurePosixPath('/work/child'), True, 0, 100)])
            pump(24)
            app = DragApp()
            app.view = view
            app.server = SimpleNamespace(connected=True, normalize=PurePosixPath)
            app.model = SimpleNamespace(normalize=Path)
            controller = TransferController(app)
            app._drop_target = controller.drop_target
            app._drop_is_valid = controller.drop_is_valid
            app._process_queued_drop = Mock()
            app._opposite_panel = Mock(side_effect=AssertionError('must not guess a target'))
            listing = view.right.listview
            source = next(row for row in listing.items if row.name == 'a.inp')
            def stale_hover():
                app._drag_target_panel = view.left
                app._drag_target_destination = view.left.current_path
                app._drag_target_point = (1, 1)
            def row_point(name):
                index = next(i for i, row in enumerate(listing.items) if row.name == name)
                rect = QRetainedItem(listing.body_window).globalGeometry()
                x, y = rect.left(), rect.top()
                return x + 70, y + index * listing.ROW_HEIGHT + listing.ROW_HEIGHT / 2
            stale_hover()
            app.drop(view.right, *row_point('a.inp'), False, dragged_items=[source])
            pump()
            app._process_queued_drop.assert_not_called()
            # Blank space in the same Server pane is also a no-op.
            rect = QRetainedItem(listing.body_window).globalGeometry()
            x, y, width, height = rect.left(), rect.top(), rect.width(), rect.height()
            stale_hover()
            app.drop(view.right, x + width / 2, y + height - 10, True, dragged_items=[source])
            pump()
            app._process_queued_drop.assert_not_called()
            stale_hover()
            app.drop(view.right, *row_point('child'), False, dragged_items=[source])
            pump()
            args = app._process_queued_drop.call_args.args
            assert args[0] is view.right and args[1] is view.right
            assert args[2] == PurePosixPath('/work/child')
            app._process_queued_drop.reset_mock()
            stale_hover()
            app.drop(view.right, 0, 0, False, dragged_items=[source])
            app.drop(view.right, 1000000, 1000000, False, dragged_items=[source])
            pump()
            app._process_queued_drop.assert_not_called()
            rect = QRetainedItem(view.left.listview.body_window).globalGeometry()
            x, y = rect.left(), rect.top()
            app.drop(view.right, x + 70, y + 40, True, dragged_items=[source])
            pump()
            assert app._process_queued_drop.call_args.args[1] is view.left
            app._opposite_panel.assert_not_called()
            print('PASS: real Server file/blank drops do not download; child stays Server; explicit Local drop routes Local; unknown/outside drops cancel')
        finally:
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
