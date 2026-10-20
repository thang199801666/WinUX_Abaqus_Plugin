"""r7: native suffix deletion retains the stable model/view prefix."""

import pytest

from DearUIQt.modelview import QListView, QTableView
from DearUIQt.modelview.models import QtGridRow, QtListItem
from tests.test_dearuiqt_inplace_rows_r5 import TrackingBackend


@pytest.fixture(autouse=True)
def stub_themes(monkeypatch):
    for name in ('table.qt_item_view_theme', 'table.qt_item_row_theme',
                 'table.qt_item_text_theme', 'list.qt_item_row_theme',
                 'list.qt_check_list_row_theme'):
        module, name = name.split('.')
        monkeypatch.setattr(f'DearUIQt.modelview.{module}.{name}',
                            lambda *_a, **_kw: 'theme')


def test_table_tail_trim_keeps_native_rows_scroll_selection_and_metadata():
    b = TrackingBackend()
    view = QTableView(backend=b, columns=['Name', 'Value'])
    view.set_rows([QtGridRow(i, (f'Row {i}', i), data={'v': i}) for i in range(1000)])
    view.setCurrentKey(50, select=True)
    b.set_y_scroll(view.tag, 540)
    retained = dict(view._row_tags)
    before_add = b.row_adds
    before_delete = b.deletes
    view.set_rows([QtGridRow(i, (f'Row {i}', i), data={'v': i + 1}) for i in range(992)])
    assert b.row_adds == before_add
    assert b.deletes - before_delete == 24  # 8 rows with 2 cells each
    assert all(view._row_tags[i] == retained[i] for i in range(992))
    assert len(view.items) == 992
    assert len(view._row_index) == 992
    assert view.rowValues(999) is None
    assert view.rowData(200) == {'v': 201}
    assert (view.current, view.selected) == (50, {50})
    assert b.get_y_scroll(view.tag) == 540


def test_table_trim_updates_surviving_prefix_values_and_disabled_state():
    b = TrackingBackend()
    view = QTableView(backend=b, columns=['Name', 'Value'])
    view.set_rows([('a', ('A', 1)), ('b', ('B', 2)), ('c', ('C', 3))])
    retained = view._row_tags['a']
    view.set_rows([QtGridRow('a', ('Updated', 5), enabled=False), ('b', ('B', 2))])
    assert view._row_tags['a'] == retained
    assert b.config[view.items['a']]['label'] == 'Updated'
    assert b.config[view.items['a']]['enabled'] is False
    assert view.rowValues('c') is None


def test_table_trim_removes_selected_tail_and_emits_selection_event():
    b = TrackingBackend()
    view = QTableView(backend=b, columns=['Name'])
    view.set_rows([(i, (str(i),)) for i in range(3)])
    view.setCurrentKey(2, select=True)
    messages = []
    view.selectionChanged.connect(lambda keys: messages.append(keys))
    view.set_rows([(0, ('0',)), (1, ('1',))])
    assert view.selected == set()
    assert messages == [set()]
    assert 2 not in view.items


def test_table_reorder_does_not_use_tail_trim():
    b = TrackingBackend()
    view = QTableView(backend=b, columns=['Name'])
    view.set_rows([(i, (str(i),)) for i in range(3)])
    old = view._row_tags[0]
    view.set_rows([(1, ('1',)), (0, ('0',))])
    assert view._row_tags[0] != old


def test_table_partial_delete_failure_recovers_through_full_rebuild():
    class FailOnce(TrackingBackend):
        fail = False
        def delete_item(self, tag):
            if self.fail:
                self.fail = False
                raise RuntimeError('delete failed')
            return super().delete_item(tag)
    b = FailOnce()
    view = QTableView(backend=b, columns=['Name'])
    view.set_rows([(i, (str(i),)) for i in range(5)])
    prior = view._row_tags[0]
    b.fail = True
    view.set_rows([(i, (str(i),)) for i in range(3)])
    assert len(view._row_tags) == 3
    assert view._row_tags[0] != prior
    assert len(b.get_item_children(view.tag, 1)) == 3


def test_list_trim_retains_checkbox_container_and_scroll():
    b = TrackingBackend()
    view = QListView(backend=b)
    incoming = [QtListItem(i, f'Value {i}', checked=(i % 2 == 0)) for i in range(300)]
    view.setItems(incoming)
    view.setCurrentKey(20, select=True)
    view.setVerticalScrollValue(120)
    retained = dict(view.items)
    checkbox = view.checkboxes[0]
    old_adds, old_deletes = b.adds, b.deletes
    view.setItems(incoming[:295])
    assert b.adds == old_adds
    assert b.deletes - old_deletes == 15  # five checkbox containers
    assert all(view.items[i] == retained[i] for i in range(295))
    assert view.checkboxes[0] == checkbox
    assert view.current == 20 and view.selected == {20}
    assert view.verticalScrollValue() == 120
    assert len(b.get_item_children(view.tag, 1)) == 295


def test_list_trim_selected_tail_clears_current_without_autoselect():
    b = TrackingBackend()
    view = QListView(backend=b)
    rows = [QtListItem(i, f'Row {i}') for i in range(4)]
    view.setItems(rows)
    view.setCurrentKey(3, select=True)
    current = []
    view.currentChanged.connect(lambda key: current.append(key))
    view.setItems(rows[:2])
    assert view.selected == set() and view.current is None
    assert current == [None]
    assert set(view.items) == {0, 1}


def test_list_trim_reorder_or_check_shape_change_rebuilds():
    b = TrackingBackend()
    view = QListView(backend=b)
    rows = [QtListItem(0, 'A', checked=False), QtListItem(1, 'B'), QtListItem(2, 'C')]
    view.setItems(rows)
    old = view.items[0]
    view.setItems([QtListItem(0, 'A', checked=True), rows[1]])
    assert view.items[0] != old


def test_list_delete_failure_rebuilds():
    class FailOnce(TrackingBackend):
        fail = False
        def delete_item(self, tag):
            if self.fail:
                self.fail = False
                raise RuntimeError('intermittent delete failure')
            return super().delete_item(tag)
    b = FailOnce()
    view = QListView(backend=b)
    rows = [QtListItem(i, str(i)) for i in range(4)]
    view.setItems(rows)
    old = view.items[0]
    b.fail = True
    view.setItems(rows[:2])
    assert view.items[0] != old
    assert len(b.get_item_children(view.tag, 1)) == 2
