"""r4: persistent list-view update and bulk insertion regression tests."""

import pytest

from DearUIQt.modelview import QListView, QListWidget, QListWidgetItem
from DearUIQt.modelview.models import QtListItem
from tests.test_dearuiqt_modelview_r79 import FakeBackend


class CountingBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.adds = 0
        self.deletes = 0
        self.value_writes = 0
        self.theme_binds = 0
        self.children_reads = 0

    def add_checkbox(self, **kwargs):
        return self._new(**kwargs)

    def add_selectable(self, **kwargs):
        self.adds += 1
        return super().add_selectable(**kwargs)

    def delete_item(self, tag):
        self.deletes += 1
        return super().delete_item(tag)

    def set_value(self, tag, value):
        self.value_writes += 1
        return super().set_value(tag, value)

    def bind_item_theme(self, *args, **kwargs):
        self.theme_binds += 1
        return super().bind_item_theme(*args, **kwargs)

    def get_item_children(self, tag, slot=1):
        self.children_reads += 1
        return super().get_item_children(tag, slot)


@pytest.fixture(autouse=True)
def lightweight_backend_themes(monkeypatch):
    # Theme construction uses native Dear PyGui APIs, which are unavailable on
    # Linux. Keep this suite concerned with renderer calls and row lifecycles.
    monkeypatch.setattr('DearUIQt.modelview.list.qt_item_row_theme', lambda *_a, **_kw: 'row-theme')
    monkeypatch.setattr('DearUIQt.modelview.list.qt_check_list_row_theme', lambda *_a, **_kw: 'check-theme')


def test_bulk_append_builds_once_and_preserves_item_identity_and_order():
    backend = CountingBackend()
    view = QListWidget(backend=backend)
    original = QListWidgetItem('First')
    values = [original] + [f'Row {i}' for i in range(100)]
    start = backend.children_reads
    results = view.addItems(values)
    assert results[0] is original
    assert view.item(0) is original
    assert view.count() == len(values)
    assert [x.text() for x in results] == ['First'] + [f'Row {i}' for i in range(100)]
    assert backend.children_reads - start == 1
    assert backend.adds == 101
    assert backend.deletes == 0


def test_bulk_append_skips_duplicate_objects_and_empty_batches():
    backend = CountingBackend()
    view = QListWidget(backend=backend)
    item = QListWidgetItem('A')
    result = view.addItems([item, item, 'B'])
    assert result[0] is result[1] is item
    assert view.count() == 2
    start = backend.children_reads
    assert view.addItems([item]) == [item]
    assert view.addItems([]) == []
    assert backend.children_reads == start


def test_bulk_append_rejects_foreign_owned_item():
    backend = CountingBackend()
    a = QListWidget(backend=backend)
    b = QListWidget(backend=backend)
    item = a.addItem('a')
    try:
        b.addItems([item])
        assert False, 'expected ValueError'
    except ValueError:
        pass
    assert a.count() == 1 and b.count() == 0


def test_identical_list_update_keeps_native_rows_and_userdata_can_change():
    backend = CountingBackend()
    view = QListView(backend=backend)
    original = [QtListItem('a', 'Alpha', {'old': True}), QtListItem('b', 'Beta')]
    view.setItems(original)
    native = dict(view.items)
    counters = backend.adds, backend.deletes, backend.value_writes, backend.children_reads
    # UserRole data can be a type with no safe truth comparison.
    class Uncomparable:
        def __eq__(self, other):
            raise AssertionError('opaque role data must not be compared')
    user_data = Uncomparable()
    view.setItems([QtListItem('a', 'Alpha', user_data), QtListItem('b', 'Beta')])
    assert view.items == native
    assert view.itemData('a') is user_data
    assert counters == (backend.adds, backend.deletes, backend.value_writes, backend.children_reads)
    view.setItems([QtListItem('a', 'Changed', user_data), QtListItem('b', 'Beta')])
    # r5: visual text changes now update the existing renderer in place.
    assert backend.adds == counters[0]
    assert backend.config[view.items['a']]['label'] == 'Changed'


def test_unchanged_selection_skips_native_writes_but_changed_selection_updates():
    backend = CountingBackend()
    view = QListView(backend=backend)
    view.setItems([QtListItem(i, f'Row {i}') for i in range(120)])
    view.setFocus()  # Focus changes legitimately repaint all existing rows.
    original = (backend.value_writes, backend.theme_binds)
    view._sync_selection_visuals()
    assert (backend.value_writes, backend.theme_binds) == original
    assert view.setCurrentKey(37, select=True)
    # Only changed rows should require native updates, not all 120.
    assert backend.value_writes - original[0] <= 2
    assert backend.theme_binds - original[1] <= 2
    original = backend.value_writes, backend.theme_binds
    assert view.setCurrentKey(38, select=True)
    assert backend.value_writes - original[0] <= 3
    assert backend.theme_binds - original[1] <= 3


def test_checkbox_row_refreshes_without_rebuild_when_displayed_check_state_changes():
    backend = CountingBackend()
    view = QListView(backend=backend)
    view.setItems([QtListItem(1, 'Check', checked=False)])
    old_native = view.items[1]
    view.setItems([QtListItem(1, 'Check', checked=True)])
    assert view.items[1] == old_native
    assert backend.get_value(view.checkboxes[1]) is True


def test_table_model_incremental_change_reuses_rows_and_skips_unchanged_values():
    from DearUIQt.modelview import QTableView
    from tests.test_dearuiqt_modelview_r79 import make_model
    backend = CountingBackend()
    view = QTableView(backend=backend)
    model = make_model()
    view.setModel(model)
    native = dict(view._row_tags)
    counter = backend.value_writes
    model.dataChanged.emit(model.index(0, 0), model.index(1, 1), [])
    assert backend.value_writes == counter
    assert view._row_tags == native
    model.setData(model.index(1, 1), 420)
    assert view.rowValues(1) == ('beta', 420)
    assert backend.value_writes == counter + 1
    assert view._row_tags == native


def test_table_range_refresh_updates_many_rows_without_rowvalues_linear_lookup(monkeypatch):
    from DearUIQt.modelview import QTableView
    from tests.test_dearuiqt_modelview_r79 import make_model
    backend = CountingBackend()
    view = QTableView(backend=backend)
    model = make_model()
    model.rows = [[f'entry {i}', i] for i in range(600)]
    view.setModel(model)
    view.setCurrentKey(333, select=True)
    # Legacy algorithm called rowValues (linear scan) for every updated row;
    # the cached index must now cover all incremental changes.
    monkeypatch.setattr(view, 'rowValues', lambda _key: (_ for _ in ()).throw(AssertionError('full scan')))
    for row in range(600):
        model.rows[row][1] = row + 10
    counter = backend.value_writes
    model.dataChanged.emit(model.index(0, 1), model.index(599, 1), [])
    assert backend.value_writes == counter + 600
    assert view.current == 333 and view.selected == {333}
    assert view.rows[0][1] == ('entry 0', 10)
    assert view.rows[-1][1] == ('entry 599', 609)


def test_table_selection_updates_only_rows_whose_state_changed(monkeypatch):
    from DearUIQt.modelview import QTableView
    from DearUIQt.modelview.models import QtGridRow
    monkeypatch.setattr('DearUIQt.modelview.table.qt_item_row_theme',
                        lambda *_args, **_kwargs: 'row-theme')
    monkeypatch.setattr('DearUIQt.modelview.table.qt_item_text_theme',
                        lambda *_args, **_kwargs: 'text-theme')
    backend = CountingBackend()
    view = QTableView(backend=backend, columns=['Name', 'Status'])
    view.set_rows([QtGridRow(i, (f'Row {i}', 'Pending')) for i in range(150)])
    view.setFocus()
    original = (backend.value_writes, backend.theme_binds)
    view._sync_selection_visuals()
    assert original == (backend.value_writes, backend.theme_binds)
    view.setCurrentKey(80, select=True)
    assert backend.value_writes - original[0] <= 2
    assert backend.theme_binds - original[1] <= 4  # Row + one cell each.
    original = (backend.value_writes, backend.theme_binds)
    view.setCurrentKey(81, select=True)
    assert backend.value_writes - original[0] <= 3
    assert backend.theme_binds - original[1] <= 6
    assert view.rowValues(80) == ('Row 80', 'Pending')
    assert view.rowValues('missing') is None
