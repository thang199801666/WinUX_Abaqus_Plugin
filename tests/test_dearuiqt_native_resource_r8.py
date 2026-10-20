"""r8: native control retention, lifecycle and opt-in diagnostic coverage."""

import pytest

from DearUIQt.modelview import (
    QListView, QListWidget, QListWidgetItem, QTableView,
    capture_view_resources,
)
from DearUIQt.modelview.models import QtListItem
from tests.test_dearuiqt_inplace_rows_r5 import TrackingBackend


@pytest.fixture(autouse=True)
def themes(monkeypatch):
    for name in ('table.qt_item_view_theme', 'table.qt_item_row_theme',
                 'table.qt_item_text_theme', 'list.qt_item_row_theme',
                 'list.qt_check_list_row_theme'):
        mod, function = name.split('.')
        monkeypatch.setattr(f'DearUIQt.modelview.{mod}.{function}',
                            lambda *_a, **_kw: 'test-theme')


def test_check_refresh_keeps_native_rows_and_only_updates_check_value():
    backend = TrackingBackend()
    view = QListView(backend=backend)
    original = [QtListItem(i, f'row {i}', checked=False) for i in range(1200)]
    view.setItems(original)
    view.setCurrentKey(27, select=True)
    view.setVerticalScrollValue(1300)
    rows = dict(view.items)
    checks = dict(view.checkboxes)
    before = (backend.adds, backend.deletes, backend.value_writes)
    changed = list(original)
    changed[934] = QtListItem(934, 'row 934', checked=True)
    view.setItems(changed)
    assert view.items == rows and view.checkboxes == checks
    assert (backend.adds, backend.deletes, backend.value_writes) == (
        before[0], before[1], before[2] + 1)
    assert backend.get_value(checks[934]) is True
    assert (view.current, view.selected) == (27, {27})
    assert view.verticalScrollValue() == 1300
    snapshot = capture_view_resources(view, verify_native=True)
    assert (snapshot.logical_rows, snapshot.tracked_native_rows,
            snapshot.checked_controls, snapshot.native_children) == (1200, 1200, 1200, 1200)
    assert snapshot.missing_native_items == 0


def test_unchecked_toggle_is_not_a_structural_change():
    backend = TrackingBackend()
    view = QListView(backend=backend)
    view.setItems([QtListItem('a', 'A', checked=True), QtListItem('b', 'B')])
    row = view.items['a']
    check = view.checkboxes['a']
    view.setItems([QtListItem('a', 'A', checked=False), QtListItem('b', 'B')])
    assert view.items['a'] == row and view.checkboxes['a'] == check
    assert backend.get_value(check) is False
    view.setItems([QtListItem('a', 'A', checked=None), QtListItem('b', 'B')])
    assert view.items['a'] != row and 'a' not in view.checkboxes


def test_backend_checkbox_write_failure_recovers_via_rebuild():
    class FailOne(TrackingBackend):
        fail_next = False
        def set_value(self, tag, value):
            if self.fail_next:
                self.fail_next = False
                raise RuntimeError('renderer lost checkbox')
            return super().set_value(tag, value)
    backend = FailOne()
    view = QListView(backend=backend)
    view.setItems([QtListItem(1, 'A', checked=False)])
    old_id = view.items[1]
    backend.fail_next = True
    view.setItems([QtListItem(1, 'A', checked=True)])
    assert view.items[1] != old_id
    assert backend.get_value(view.checkboxes[1]) is True


def test_resource_snapshot_tracks_native_table_rows_before_and_after_trim():
    b = TrackingBackend()
    view = QTableView(backend=b, columns=['Key', 'Value'])
    view.set_rows([(i, (str(i), i)) for i in range(200)])
    snapshot = capture_view_resources(view, verify_native=True)
    assert snapshot.view_kind == 'table'
    assert snapshot.tracked_native_rows == 200
    assert snapshot.tracked_controls == 400
    assert snapshot.native_children == 200 and snapshot.missing_native_items == 0
    view.set_rows([(i, (str(i), i)) for i in range(195)])
    after = capture_view_resources(view, verify_native=True)
    assert (after.tracked_native_rows, after.native_children, after.missing_native_items) == (195, 195, 0)


def test_resource_snapshots_are_opt_in_and_do_not_query_renderer():
    b = TrackingBackend()
    view = QListView(backend=b)
    view.setItems([QtListItem(0, 'a')])
    before = b.children_reads
    snapshot = capture_view_resources(view)
    assert snapshot.native_children is None and snapshot.missing_native_items is None
    assert b.children_reads == before
    with pytest.raises(TypeError):
        capture_view_resources(object())


def test_owned_items_and_native_handles_released_on_listwidget_delete():
    b = TrackingBackend()
    widget = QListWidget(backend=b)
    item = QListWidgetItem('A')
    widget.addItem(item)
    view_tag = widget.tag
    assert item._owner is widget
    widget.delete()
    assert item._owner is None
    assert not b.does_item_exist(view_tag)
    assert not b.does_item_exist(widget.items.get(item.key))
    widget.delete()  # Idempotent


def test_repeated_view_deletion_releases_global_mouse_handlers():
    # The fake backend must mimic Dear PyGui handler_registry's implicit
    # parenting; a handler is a native child of its registry, not an orphan.
    from contextlib import contextmanager

    class NativeLikeBackend(TrackingBackend):
        _active_registry = None

        @contextmanager
        def handler_registry(self):
            registry = self._new()
            previous = self._active_registry
            self._active_registry = registry
            try:
                yield registry
            finally:
                self._active_registry = previous

        def add_mouse_click_handler(self, **kwargs):
            return self._new(parent=self._active_registry, **kwargs)

    backend = NativeLikeBackend()
    for _ in range(30):
        view = QListView(backend=backend, context_menu_requests=True)
        view.setItems([QtListItem(i, str(i), checked=False) for i in range(40)])
        assert len(backend.config) > 0
        view.delete()
        view.delete()  # deletion must be idempotent
        assert len(backend.config) == 0
    for _ in range(30):
        table = QTableView(backend=backend, columns=['A', 'B'])
        table.set_rows([(i, (str(i), i)) for i in range(40)])
        table.delete()
        assert len(backend.config) == 0
