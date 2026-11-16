import time

import DearUIQt
from DearUIQt import (QEvent, QEventDispatcher, QGuiEventType, QGuiRuntime,
                      QPopupSurface, QWindowHost, isGuiEventType)
from WinUx.runtime.ui_dispatcher import UiDispatcher


def test_qeventdispatcher_keyed_post_coalesces_and_releases_before_delivery():
    dispatcher = QEventDispatcher()
    delivered = []

    first = dispatcher.post(delivered.append, "first", key="refresh")
    duplicate = dispatcher.post(delivered.append, "duplicate", key="refresh")
    assert first is not None
    assert duplicate is None
    assert dispatcher.hasCoalescedKey("refresh")
    assert dispatcher.diagnosticsSnapshot()["coalesced_count"] == 1

    def repost():
        delivered.append("callback")
        # Key must already be released before callback delivery begins.
        assert dispatcher.post(delivered.append, "next", key="refresh") is not None

    assert dispatcher.after_cancel(first)
    assert not dispatcher.hasCoalescedKey("refresh")
    assert dispatcher.post(repost, key="refresh") is not None
    assert dispatcher.processEvents(max_callbacks=None, time_budget_ms=None) == 1
    assert delivered == ["callback"]
    assert dispatcher.processEvents(max_callbacks=None, time_budget_ms=None) == 1
    assert delivered == ["callback", "next"]
    dispatcher.close()


def test_ui_dispatcher_is_canonical_facade_with_keyed_compatibility():
    dispatcher = UiDispatcher()
    delivered = []
    assert dispatcher.post(delivered.append, 1, key="same") is True
    assert dispatcher.post(delivered.append, 2, key="same") is False
    snap = dispatcher.diagnosticsSnapshot()
    assert snap["canonical_dispatcher"] is True
    assert snap["coalesced_posts"] == 1
    assert dispatcher.processEvents(max_callbacks=None, time_budget_ms=None) == 1
    assert delivered == [1]
    assert dispatcher.post(delivered.append, 3, key="same") is True
    assert dispatcher.processEvents(max_callbacks=None, time_budget_ms=None) == 1
    assert delivered == [1, 3]
    dispatcher.close()


def test_window_host_and_popup_teardown_share_correlation_id():
    host = QWindowHost(close=lambda: True)
    popup = QPopupSurface()
    popup.beginShow(host=host, geometry=(1, 2, 30, 40))
    popup.markVisible()

    popup_before = popup.diagnosticsSnapshot()
    host_before = host.diagnosticsSnapshot()
    assert popup_before["host_correlation_id"] == host_before["correlation_id"]
    assert popup_before["last_teardown_correlation_id"] is None

    assert host.close(reason="owner_destroyed") is True
    host_after = host.diagnosticsSnapshot()
    popup_after = popup.diagnosticsSnapshot()
    assert host_after["teardown_correlation_id"]
    assert popup_after["last_teardown_correlation_id"] == host_after["teardown_correlation_id"]
    assert popup_after["last_hide_reason"] == "host_closing"
    assert popup_after["state"] == popup.Hidden


def test_idle_render_health_has_quantitative_thresholds_and_is_read_only():
    class Backend:
        pass

    runtime = QGuiRuntime(Backend())
    host = runtime.windowHost()
    host.setGeometry((0, 0, 100, 80))
    host.requestUpdate((1, 2, 3, 4))
    dirty_before = host.dirtyRegion()

    now = time.monotonic()
    runtime._frame_history.clear()
    runtime._frame_history.extend([
        (now - 4.0, "skipped", "idle", 100.0),
        (now - 3.0, "skipped", "idle", 100.0),
        (now - 2.0, "skipped", "idle", 100.0),
        (now - 1.0, "rendered", None, 0.0),
    ])
    healthy = runtime.idleRenderHealthSnapshot(
        window_seconds=5.0, max_idle_render_hz=1.0, min_idle_fraction=0.70)
    unhealthy = runtime.idleRenderHealthSnapshot(
        window_seconds=5.0, max_idle_render_hz=0.10, min_idle_fraction=0.90)

    assert healthy["within_threshold"] is True
    assert unhealthy["within_threshold"] is False
    dirty_after = host.dirtyRegion()
    assert (dirty_before.x(), dirty_before.y(), dirty_before.width(), dirty_before.height()) == (
        dirty_after.x(), dirty_after.y(), dirty_after.width(), dirty_after.height())



def test_gui_event_type_namespace_preserves_values_without_core_policy_dependency():
    assert int(QGuiEventType.KeyPress) == QEvent.KeyPress
    assert int(QGuiEventType.MouseButtonPress) == QEvent.MouseButtonPress
    assert isGuiEventType(QEvent.KeyPress) is True
    assert isGuiEventType(QEvent.LayoutRequest) is False


def test_m17_version_floor():
    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 141, 0)
