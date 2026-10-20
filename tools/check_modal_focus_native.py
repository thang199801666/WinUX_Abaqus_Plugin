"""Verify modal focus confinement against stale native requests, without mouse injection."""
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1])
    import dearpygui.dearpygui
import WinUx
from WinUx.controllers import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView
from WinUx.ui.behaviors.plot_docking import PlotDockingMixin
from DearUIQt.backends import get_backend
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets.widget import QWidget


def main():
    errors = []
    with patch.object(PlotDockingMixin, "_get_reference_chart_library",
                      lambda self: SimpleNamespace(snapshot=lambda: [], replace=Mock())):
        view = WinUXView({name: Mock(return_value=[]) for name in REQUIRED_CALLBACK_KEYS})
        view._handle_ui_callback_error = lambda callback, info: errors.append(info[1])
        backend = get_backend()
        state = backend.internal_dpg.dearuiqt_native_input_state
        dialogs = []
        def frame_barrier():
            target = backend.get_frame_count() + 3
            return lambda: backend.get_frame_count() >= target
        def scenario():
            parent = QtDialog(view, "Focus boundary parent", 500, 230)
            parent.action("Action", lambda: None)
            dialogs.append(parent)
            yield "parent rendered", lambda: parent.winId()
            yield "parent settled", frame_barrier()
            background = QWidget(view.primary_window_tag, backend=backend)
            assert not background.setFocus(), "QWidget queued background focus behind a modal"
            # Bypass Python to simulate a native focus request queued BEFORE the
            # modal opened. The renderer must enforce the same owner boundary.
            backend.focus_item(view.primary_window_tag)
            yield "stale parent focus drained", frame_barrier()
            assert state()["nav_window"].startswith("Focus boundary parent###"), state()
            child = QtDialog(view, "Focus boundary child", 400, 210, parent=parent)
            child.action("Action", lambda: None)
            dialogs.append(child)
            yield "child rendered", lambda: child.winId()
            yield "child settled", frame_barrier()
            assert not background.setFocus()
            backend.focus_item(view.primary_window_tag)
            yield "nested stale focus drained", frame_barrier()
            assert state()["nav_window"].startswith("Focus boundary child###"), state()
            child.destroy()
            yield "child closed", frame_barrier()
            backend.focus_item(view.primary_window_tag)
            yield "parent restored", frame_barrier()
            assert state()["nav_window"].startswith("Focus boundary parent###"), state()
            parent.destroy()
            yield "parent closed", frame_barrier()
        steps, pending = scenario(), []
        def advance():
            try:
                if errors:
                    raise errors[0]
                if pending:
                    label, predicate, deadline = pending[0]
                    if not predicate():
                        assert time.monotonic() < deadline, "Timeout: " + label
                        view.after(10, advance)
                        return
                    pending.clear()
                label, predicate = next(steps)
                pending.append((label, predicate, time.monotonic() + 5))
                view.after(10, advance)
            except StopIteration:
                view.request_shutdown()
            except Exception as exc:
                errors.append(exc)
                view.request_shutdown()
        view.after(200, advance)
        view.run()
        if errors:
            raise errors[0]
    print("MODAL_FOCUS_NATIVE_OK: background QWidget, queued native focus, nested modal and return to parent")


if __name__ == "__main__":
    main()
