import time

from DearUIQt import QCoreApplication, QApplication, QGuiRuntime
from DearUIQt.gui.window_host import QWindowHost


def _cleanup_app():
    app = QCoreApplication.instance()
    if app is not None:
        app.delete()


def test_qcore_has_no_gui_input_focus_shortcut_api():
    _cleanup_app()
    app = QCoreApplication(after=lambda delay, callback, *args: None)
    try:
        for name in (
            'registerShortcut', 'unregisterShortcut', 'installInputBackend',
            'removeInputBackend', 'registerPointerTarget', 'dispatchPointerEvent',
            'dispatchKeyEvent', 'focusWidget', 'focusObject', 'activeWindow',
            'activePopupWidget', 'activeModalWidget', 'setFocusWidget',
            'setFocusObject', 'setActiveWindow',
        ):
            assert not hasattr(app, name), name
    finally:
        app.delete()


def test_qapplication_owns_gui_input_focus_shortcut_api():
    _cleanup_app()
    app = QApplication(after=lambda delay, callback, *args: None)
    try:
        assert callable(app.registerShortcut)
        assert callable(app.installInputBackend)
        assert callable(app.dispatchPointerEvent)
        assert callable(app.dispatchKeyEvent)
        assert app.focusObject() is None
        assert app.activeWindow() is None
    finally:
        app.delete()


def test_window_host_explicit_state_machine_and_rejected_close():
    transitions = []
    host = QWindowHost(close=lambda: False)
    host.stateChanged.connect(transitions.append)
    assert host.state() == host.Alive
    assert host.isAlive()
    assert host.close() is False
    assert host.state() == host.Alive
    assert transitions == [host.Closing, host.Alive]

    host._close = lambda: True
    assert host.close() is True
    assert host.state() == host.Closed
    assert transitions[-2:] == [host.Closing, host.Closed]
    assert host.requestUpdate() is False
    assert host.activate() is False


def test_frame_rolling_diagnostics_are_read_only():
    class Backend:
        def is_dearpygui_running(self):
            return True
        def render_dearpygui_frame(self):
            pass

    runtime = QGuiRuntime(Backend())
    host = runtime.windowHost()
    host.setGeometry((0, 0, 100, 100))
    host.requestUpdate((1, 2, 3, 4))
    before = host.dirtyRegion()
    runtime.noteFrameSkipped('idle', 12.5)
    snapshot = runtime.frameDiagnosticsSnapshot()
    after = host.dirtyRegion()
    assert before is not None and after is not None
    assert (before.x(), before.y(), before.width(), before.height()) == (after.x(), after.y(), after.width(), after.height())
    assert snapshot['rolling_5s']['skipped'] >= 1
    assert snapshot['rolling_5s']['rendered'] == 0
    assert snapshot['host']['state'] == host.Alive
