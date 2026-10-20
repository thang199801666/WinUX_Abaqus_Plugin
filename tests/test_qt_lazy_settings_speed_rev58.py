from collections import deque
from pathlib import Path

from DearUIQt.qt.application import QApplication
from DearUIQt.qt.core import QEvent, QObject
from DearUIQt.qt.widget import QWidget

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

    def configure_item(self, tag, **kwargs):
        self.config.setdefault(tag, {}).update(kwargs)

    def get_item_configuration(self, tag):
        return dict(self.config.get(tag, {}))

    def get_item_parent(self, tag):
        return 0

    def does_item_exist(self, tag):
        return True

    def delete_item(self, tag):
        pass


class Receiver(QWidget):
    def __init__(self, *args, **kwargs):
        self.layout_events = 0
        super().__init__(*args, **kwargs)

    def event(self, event):
        if event.type() == QEvent.LayoutRequest:
            self.layout_events += 1
        return super().event(event)


def test_widget_layout_requests_share_one_qapplication_wakeup():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        backend = FakeBackend()
        first = Receiver(1, after=scheduler.after, backend=backend)
        second = Receiver(2, after=scheduler.after, backend=backend)
        for _ in range(8):
            first.updateGeometry()
            second.updateGeometry()
        # QApplication compresses each receiver and schedules one UI turn for
        # the whole application rather than one callback per widget/dialog.
        assert len(scheduler.pending) == 1
        scheduler.pump()
        assert first.layout_events == 1
        assert second.layout_events == 1
    finally:
        app.delete()


def test_settings_first_open_builds_only_general_page():
    source = (ROOT / "WinUx/dialogs/settings_form.py").read_text(encoding="utf-8")
    init = source[source.index("    def __init__(self, view"):source.index("    def _set_status")]
    assert 'self._ensure_page("general")' in init
    assert "PerformancePreferences().load()" not in init
    assert "UpdatePreferences().load()" not in init
    assert "AbaqusVersionPreferences().load_settings" not in init
    assert "collect_update_diagnostics" not in init
    assert "LoginPreferences().load()" not in init


def test_settings_hidden_page_io_is_lazy_and_page_scoped():
    source = (ROOT / "WinUx/dialogs/settings_form.py").read_text(encoding="utf-8")
    page_data = source[source.index("    def _page_data"):source.index("    def _ensure_page")]
    assert 'key == "updates"' in page_data and "UpdatePreferences().load()" in page_data
    assert 'key == "performance"' in page_data and "PerformancePreferences().load()" in page_data
    assert 'key == "abaqus"' in page_data and "AbaqusVersionPreferences().load_settings" in page_data
    ensure = source[source.index("    def _ensure_page"):source.index("    def _ensure_all_pages")]
    assert 'self.view.after(0, self._refresh_update_recovery)' in ensure
    assert 'self.view.after(0, self._refresh_login)' in ensure


def test_settings_all_page_operations_materialize_deferred_pages():
    source = (ROOT / "WinUx/dialogs/settings_form.py").read_text(encoding="utf-8")
    reset = source[source.index("    def _reset_settings_defaults"):source.index("    def _edit_version")]
    save = source[source.index("    def _save(self):"):]
    assert "self._ensure_all_pages()" in reset
    assert "self._ensure_all_pages()" in save


def test_job_schedule_reopen_avoids_double_refresh_when_hidden():
    source = (ROOT / "WinUx/view.py").read_text(encoding="utf-8")
    block = source[source.index("    def show_job_schedule(self):"):source.index("    def edit_job", source.index("    def show_job_schedule(self):"))]
    assert "was_visible" in block
    assert "dialog.lift()" in block
    assert "if was_visible:" in block
    assert block.index("dialog.lift()") < block.index("if was_visible:")


def test_deferred_delete_uses_shared_qapplication_turn():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        backend = FakeBackend()
        first = QWidget(1, after=scheduler.after, backend=backend)
        second = QWidget(2, after=scheduler.after, backend=backend)
        first.deleteLater()
        second.deleteLater()
        assert len(scheduler.pending) == 1
        assert not first._deleted and not second._deleted
        scheduler.pump()
        assert first._deleted and second._deleted
    finally:
        app.delete()


class EventReceiver(QObject):
    def __init__(self, *args, **kwargs):
        self.count = 0
        super().__init__(*args, **kwargs)

    def event(self, event):
        if event.type() >= QEvent.User:
            self.count += 1
            return True
        return super().event(event)


def test_qapplication_posted_event_storm_yields_between_render_turns():
    scheduler = Scheduler()
    app = QApplication(after=scheduler.after)
    try:
        receiver = EventReceiver(after=scheduler.after)
        for index in range(200):
            app.postEvent(receiver, QEvent(QEvent.User + index))
        assert len(scheduler.pending) == 1
        scheduler.pump_one()
        assert receiver.count == 128
        assert len(scheduler.pending) == 1
        scheduler.pump()
        assert receiver.count == 200
    finally:
        app.delete()
