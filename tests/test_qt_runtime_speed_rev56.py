from collections import deque
from pathlib import Path

from DearUIQt.dispatch import LatestCallQueue
from DearUIQt.qt.application import QApplication
from DearUIQt.qt.core import QEvent
from DearUIQt.qt.widget import QWidget
from WinUx.ui.hosting.host import QDialogHostManager

ROOT = Path(__file__).resolve().parents[1]


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)

    def pump_one(self):
        callback, args = self.pending.popleft()
        callback(*args)

    def pump(self):
        while self.pending:
            self.pump_one()


class FakeBackend:
    def __init__(self):
        self.config = {1: {"show": True}, 2: {"show": True}}
        self.configure_calls = []
        self.focused = None
        self.deleted = set()

    def configure_item(self, tag, **kwargs):
        self.configure_calls.append((tag, dict(kwargs)))
        self.config.setdefault(tag, {}).update(kwargs)

    def get_item_configuration(self, tag):
        return dict(self.config.get(tag, {}))

    def get_item_parent(self, tag):
        return 0 if tag == 1 else 1

    def does_item_exist(self, tag):
        return tag not in self.deleted

    def focus_item(self, tag):
        self.focused = tag

    def get_item_state(self, tag):
        return {"focused": tag == self.focused}

    def delete_item(self, tag):
        self.deleted.add(tag)


class Receiver(QWidget):
    def __init__(self, *args, **kwargs):
        self.events = []
        super().__init__(*args, **kwargs)

    def event(self, event):
        self.events.append(event.type())
        return super().event(event)


class DummyView:
    def __init__(self, limit=2):
        self._dialog_resident_limit = limit
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))


class DummyResident:
    def __init__(self, name):
        self.name = name
        self._closed = False
        self._resident_generation = 1
        self.evictions = []

    def _evict_retained(self, generation):
        self.evictions.append(generation)


def test_widget_fixed_size_uses_one_native_configure_transaction():
    backend = FakeBackend()
    widget = QWidget(1, backend=backend)
    widget.setFixedSize(640, 480)
    assert backend.configure_calls == [(1, {"width": 640, "height": 480})]


def test_hiding_parent_clears_descendant_focus_like_qt():
    scheduler = Scheduler()
    backend = FakeBackend()
    app = QApplication(after=scheduler.after)
    try:
        parent = QWidget(1, after=scheduler.after, backend=backend)
        child = QWidget(2, parent=parent, after=scheduler.after, backend=backend)
        app._set_focus_widget(child)
        assert app.focusWidget() is child
        parent.hide()
        assert app.focusWidget() is None
    finally:
        app.delete()


def test_remove_posted_events_purges_deleted_receiver_work():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        backend = FakeBackend()
        widget = Receiver(1, after=scheduler.after, backend=backend)
        app.postEvent(widget, QEvent(QEvent.LayoutRequest))
        assert app.removePostedEvents(widget) == 1
        scheduler.pump()
        assert QEvent.LayoutRequest not in widget.events
    finally:
        app.delete()


def test_latest_queue_yields_large_update_storm_across_ui_turns():
    scheduler = Scheduler()
    queue = LatestCallQueue(scheduler.after, max_batch=8)
    values = []
    for index in range(25):
        queue.post(index, values.append, index)
    assert len(scheduler.pending) == 1
    scheduler.pump_one()
    assert values == list(range(8))
    assert len(scheduler.pending) == 1
    scheduler.pump_one()
    assert values == list(range(16))
    scheduler.pump()
    assert values == list(range(25))


def test_resident_dialog_cache_evicts_oldest_hidden_tool_only():
    view = DummyView(limit=2)
    manager = QDialogHostManager(view, pool=None)
    first, second, third = [DummyResident(name) for name in ("first", "second", "third")]
    manager.retained_hidden(first)
    manager.retained_hidden(second)
    manager.retained_hidden(third)
    assert list(manager._resident_hidden) == [second, third]
    assert len(view.pending) == 1
    callback, args = view.pending.popleft()
    callback(*args)
    assert first.evictions == [1]
    assert not second.evictions and not third.evictions


def test_hidden_workers_preimport_only_process_hosted_common_forms_by_default():
    source = (ROOT / "WinUx/dialogs/floating_forms.py").read_text(encoding="utf-8")
    warm = source[source.index("def prepare_common_form_imports"):source.index("def create_form")]
    base_block = warm[warm.index("modules = ["):warm.index("]", warm.index("modules = [")) + 1]
    for module in ("blocking_form", "login_form", "local_folder_form", "local_file_form"):
        assert '"{}"'.format(module) in base_block
    for module in ("settings_form", "job_schedule_form", "bookmarks_form",
                   "site_manager_form", "sync_preview_form", "diagnostics_form",
                   "transfer_center_form"):
        assert '"{}"'.format(module) not in base_block
    assert "if not use_inprocess:" in warm


def test_reopenable_main_menu_tools_use_retained_qt_lifetime():
    source = (ROOT / "WinUx/dialogs/floating_adapters.py").read_text(encoding="utf-8")
    ranges = [
        ("class DiagnosticsDialog", "class BookmarksDialog"),
        ("class BookmarksDialog", "class SiteManagerDialog"),
        ("class SiteManagerDialog", "class SyncPreviewDialog"),
        ("class SyncPreviewDialog", "class LocalFolderDialog"),
    ]
    for start, end in ranges:
        block = source[source.index(start):source.index(end)]
        assert "retain_on_close=True" in block


def test_hidden_retained_runtime_uses_native_wait_not_polling_sleep():
    runtime = (ROOT / "WinUx/ui/hosting/floating_runtime.py").read_text(encoding="utf-8")
    pump = (ROOT / "WinUx/ui/native/message_pump.py").read_text(encoding="utf-8")
    assert "wait_native_messages(12)" in runtime
    assert "time.sleep(.012)" not in runtime
    assert "MsgWaitForMultipleObjects" in pump
    assert "wake_native_window" in runtime


def test_runtime_show_hide_skip_redundant_native_visibility_calls():
    source = (ROOT / "WinUx/ui/hosting/floating_runtime.py").read_text(encoding="utf-8")
    show_block = source[source.index("    def show(self):", source.index("class FloatingDialogRuntime")):
                        source.index("    def hide(self", source.index("    def show(self):", source.index("class FloatingDialogRuntime")))]
    hide_start = source.index("    def hide(self", source.index("class FloatingDialogRuntime"))
    hide_block = source[hide_start:source.index("    def _resident_close", hide_start)]
    assert "if not self.native.visible" in show_block
    assert "if not self.native.is_foreground()" in show_block
    assert "if self.native.visible" in hide_block
