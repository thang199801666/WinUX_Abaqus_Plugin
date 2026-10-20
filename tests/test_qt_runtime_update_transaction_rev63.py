from collections import deque

from DearUIQt.qt import QApplication, QWidget


class Scheduler:
    def __init__(self):
        self.pending = deque()

    def after(self, _delay, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)

    def pump_one(self):
        callback, args = self.pending.popleft()
        return callback(*args)

    def pump(self):
        while self.pending:
            self.pump_one()


class Backend:
    def __init__(self):
        self.config = {}
        self.calls = []
        self.focused = None
        self.deleted = set()

    def configure_item(self, tag, **values):
        self.calls.append((tag, dict(values)))
        self.config.setdefault(tag, {}).update(values)

    def does_item_exist(self, tag):
        return tag not in self.deleted

    def get_item_parent(self, _tag):
        return 0

    def get_item_configuration(self, tag):
        return dict(self.config.get(tag, {}))

    def get_item_state(self, tag):
        return {"focused": self.focused == tag}

    def focus_item(self, tag):
        self.focused = tag

    def delete_item(self, tag):
        self.deleted.add(tag)


def test_runtime_widget_config_is_merged_per_widget_and_shares_application_turn():
    scheduler = Scheduler()
    backend = Backend()
    app = QApplication(after=scheduler.after)
    try:
        widget = QWidget(1, backend=backend, after=scheduler.after)
        widget.resize(100, 30)
        widget.move(7, 9)
        widget.setEnabled(False)
        widget.resize(140, 40)

        # Retained Qt state is synchronous; DearPyGui mutation is deferred.
        assert widget.width() == 140
        assert widget.height() == 40
        assert widget.isEnabled() is False
        assert backend.calls == []
        # Native update + LayoutRequest use one QApplication wake-up.
        assert len(scheduler.pending) == 1

        scheduler.pump_one()
        assert len(backend.calls) == 1
        tag, values = backend.calls[0]
        assert tag == 1
        assert values == {
            "width": 140,
            "height": 40,
            "pos": (7, 9),
            "enabled": False,
        }
    finally:
        app.delete()


def test_runtime_transaction_batches_multiple_widgets_in_one_ui_turn():
    scheduler = Scheduler()
    backend = Backend()
    app = QApplication(after=scheduler.after)
    try:
        first = QWidget(1, backend=backend, after=scheduler.after)
        second = QWidget(2, backend=backend, after=scheduler.after)
        first.move(1, 2)
        second.move(3, 4)
        first.setEnabled(False)
        second.resize(88, 24)
        assert len(scheduler.pending) == 1

        scheduler.pump_one()
        assert len(backend.calls) == 2
        by_tag = {tag: values for tag, values in backend.calls}
        assert by_tag[1] == {"pos": (1, 2), "enabled": False}
        assert by_tag[2] == {"pos": (3, 4), "width": 88, "height": 24}
    finally:
        app.delete()


def test_focus_flushes_pending_visibility_before_native_focus():
    scheduler = Scheduler()
    backend = Backend()
    app = QApplication(after=scheduler.after)
    try:
        widget = QWidget(1, backend=backend, after=scheduler.after)
        widget.hide()
        scheduler.pump()
        backend.calls.clear()
        widget.show()
        assert backend.calls == []

        assert widget.setFocus() is True
        assert backend.calls == [(1, {"show": True})]
        assert backend.focused == 1
    finally:
        app.delete()


def test_deleting_widget_discards_deferred_native_transaction():
    scheduler = Scheduler()
    backend = Backend()
    app = QApplication(after=scheduler.after)
    try:
        widget = QWidget(1, backend=backend, after=scheduler.after)
        widget.move(20, 30)
        assert widget in app._native_updates
        widget.delete()
        assert widget not in app._native_updates
        scheduler.pump()
        # No configure may be emitted after the native item was deleted.
        assert backend.calls == []
        assert 1 in backend.deleted
    finally:
        app.delete()
