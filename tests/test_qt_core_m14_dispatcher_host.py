import gc

from DearUIQt import QAbstractEventDispatcher, QCoreApplication, QApplication, QGuiRuntime
from DearUIQt.core.dispatcher import QEventDispatcher
from DearUIQt.gui.window_host import QWindowHost
from WinUx.runtime.ui_dispatcher import UiDispatcher


def _delete_app():
    app = QCoreApplication.instance()
    if app is not None:
        app.delete()
    gc.collect()


def test_dispatchers_share_public_contract_and_priority():
    for dispatcher in (QEventDispatcher(), UiDispatcher()):
        assert isinstance(dispatcher, QAbstractEventDispatcher)
        order = []
        dispatcher.post(lambda: order.append("low"), priority=-1)
        dispatcher.post(lambda: order.append("high"), priority=10)
        dispatcher.post(lambda: order.append("normal"), priority=0)
        dispatcher.processEvents(max_callbacks=8, time_budget_ms=50)
        assert order == ["high", "normal", "low"]
        assert dispatcher.ownerThreadId()
        assert dispatcher.isOwnerThread()
        assert "next_deadline_ms" in dispatcher.diagnosticsSnapshot()
        dispatcher.close()


def test_qcoreapplication_no_longer_exposes_style_palette_api():
    _delete_app()
    app = QCoreApplication()
    try:
        assert not hasattr(app, "style")
        assert not hasattr(app, "palette")
        assert not hasattr(app, "setStyle")
        assert not hasattr(app, "setPalette")
    finally:
        app.delete()


def test_qapplication_keeps_style_palette_api():
    _delete_app()
    app = QApplication()
    try:
        assert app.style() is not None
        palette = app.palette()
        app.setPalette(palette)
        assert app.palette() == palette
    finally:
        app.delete()


def test_window_host_tracks_application_owner_weakly():
    _delete_app()
    app = QApplication()
    host = QWindowHost()
    try:
        assert host.setOwnerObject(app)
        assert host.ownerObject() is app
        snap = host.diagnosticsSnapshot()
        assert snap["owner_alive"] is True
        assert snap["owner_type"] == "QApplication"
        app.delete()
        assert host.ownerObject() is None
        assert host.isClosed()
    finally:
        if not host._deleted:
            host.delete()
        _delete_app()


def test_qguiruntime_frame_diagnostics_are_side_effect_free_for_host_damage():
    class Backend:
        pass

    runtime = QGuiRuntime(Backend())
    host = runtime.windowHost()
    host.setGeometry((0, 0, 100, 50))
    host.requestUpdate((1, 2, 3, 4))
    before = host.dirtyRegion()
    snap = runtime.frameDiagnosticsSnapshot()
    after = host.dirtyRegion()
    assert snap["host"]["dirty_region"] == (1, 2, 3, 4)
    assert (before.x(), before.y(), before.width(), before.height()) == (
        after.x(), after.y(), after.width(), after.height())
    runtime.noteFrameSkipped("idle", 12.5)
    snap = runtime.frameDiagnosticsSnapshot()
    assert snap["skipped_frames"] == 1
    assert snap["last_skip_reason"] == "idle"
    assert snap["last_wait_ms"] == 12.5
