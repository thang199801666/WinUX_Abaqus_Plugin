"""r6: append-only native row reuse and failure recovery in DearUIQt item views."""

import pytest

from DearUIQt.modelview import QListView, QListWidget, QTableView
from DearUIQt.modelview.models import QtGridRow, QtListItem
from tests.test_dearuiqt_inplace_rows_r5 import TrackingBackend


@pytest.fixture(autouse=True)
def stub_themes(monkeypatch):
    for name in ('table.qt_item_view_theme', 'table.qt_item_row_theme',
                 'table.qt_item_text_theme', 'list.qt_item_row_theme',
                 'list.qt_check_list_row_theme'):
        module, name = name.split('.')
        monkeypatch.setattr(f'DearUIQt.modelview.{module}.{name}', lambda *_a, **_kw: 'theme')


def test_table_append_reuses_existing_rows_scroll_and_selection():
    backend = TrackingBackend()
    table = QTableView(backend=backend, columns=['Name', 'Count'])
    table.set_rows([(i, (f'Item {i}', i)) for i in range(1000)])
    table.setCurrentKey(50, select=True)
    backend.set_y_scroll(table.tag, 650.0)
    old_native = dict(table._row_tags)
    old_cells = dict(table.items)
    old_created = backend.row_adds
    old_deleted = backend.deletes
    table.set_rows([(i, (f'Item {i}', i)) for i in range(1003)])
    assert backend.row_adds - old_created == 3
    assert backend.deletes == old_deleted
    assert all(table._row_tags[i] == old_native[i] for i in range(1000))
    assert all(table.items[i] == old_cells[i] for i in range(1000))
    assert table.rowValues(1002) == ('Item 1002', 1002)
    assert table.current == 50 and table.selected == {50}
    assert backend.get_y_scroll(table.tag) == 650.0


def test_table_append_updates_prefix_only_when_value_changed():
    backend = TrackingBackend()
    table = QTableView(backend=backend, columns=['Name', 'Count'])
    table.set_rows([('a', ('Alpha', 1)), ('b', ('Beta', 2))])
    old_tags = dict(table._row_tags)
    old_cell = table._cell_native_items['b'][1]
    table.set_rows([('a', ('Updated', 1)), ('b', ('Beta', 20)), ('c', ('Gamma', 3))])
    assert all(table._row_tags[k] == v for k, v in old_tags.items())
    assert backend.config[table.items['a']]['label'] == 'Updated'
    assert backend.values[old_cell] == '20'
    assert table.rowValues('c') == ('Gamma', 3)


def test_table_append_preserves_row_backgrounds_and_enabled_state():
    backend = TrackingBackend()
    table = QTableView(backend=backend, columns=['Name'])
    table.set_rows([QtGridRow('old', ('Old',), enabled=True)])
    old_tag = table._row_tags['old']
    table.set_rows([
        QtGridRow('old', ('Old',), enabled=False),
        QtGridRow('new', ('New',), background=(24, 120, 255, 255)),
    ])
    assert table._row_tags['old'] == old_tag
    assert backend.config[table.items['old']]['enabled'] is False
    assert (1, (24, 120, 255, 255)) in backend.highlights


def test_table_reorder_and_shape_changes_do_not_use_append_fast_path():
    backend = TrackingBackend()
    table = QTableView(backend=backend, columns=['Name', 'Value'])
    table.set_rows([('a', ('A', 1)), ('b', ('B', 2))])
    original = dict(table._row_tags)
    table.set_rows([('b', ('B', 2)), ('a', ('A', 1)), ('c', ('C', 3))])
    assert table._row_tags['a'] != original['a']
    original = dict(table._row_tags)
    table.set_rows([('b', ('B',)), ('a', ('A', 1)), ('c', ('C', 3)), ('d', ('D', 4))])
    assert table._row_tags['a'] != original['a']


def test_list_append_preserves_existing_checkboxes_selection_and_scroll():
    backend = TrackingBackend()
    view = QListView(backend=backend)
    view.setItems([QtListItem('a', 'Alpha', checked=True), QtListItem('b', 'Beta')])
    view.setCurrentKey('b', select=True)
    view.setVerticalScrollValue(44)
    original = dict(view.items)
    check = view.checkboxes['a']
    prior_adds = backend.adds
    prior_deletes = backend.deletes
    view.setItems([
        QtListItem('a', 'Alpha', checked=True), QtListItem('b', 'Beta'),
        QtListItem('c', 'Gamma', checked=False), QtListItem('d', 'Delta'),
    ])
    assert backend.adds - prior_adds == 2
    assert backend.deletes == prior_deletes
    assert view.items['a'] == original['a'] and view.items['b'] == original['b']
    assert view.checkboxes['a'] == check and 'c' in view.checkboxes
    assert view.selected == {'b'} and view.current == 'b'
    assert view.verticalScrollValue() == 44


def test_qlistwidget_append_after_initial_add_only_materializes_suffix():
    backend = TrackingBackend()
    view = QListWidget(backend=backend)
    first = view.addItems([f'Item {i}' for i in range(250)])
    native = view.items[first[4].key]
    previous_adds, previous_deletes = backend.adds, backend.deletes
    new = view.addItems(['New A', 'New B'])
    assert backend.adds - previous_adds == 2
    assert backend.deletes == previous_deletes
    assert view.items[first[4].key] == native
    assert view.item(251) is new[1]


def test_list_prefix_changed_checkbox_forces_rebuild():
    backend = TrackingBackend()
    view = QListView(backend=backend)
    view.setItems([QtListItem(1, 'X', checked=False)])
    prev = view.items[1]
    view.setItems([QtListItem(1, 'X', checked=True), QtListItem(2, 'Y')])
    assert view.items[1] != prev


def test_backend_failure_during_append_falls_back_to_full_native_rebuild():
    class FailingBackend(TrackingBackend):
        fail_once = False

        def add_table_row(self, **kwargs):
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError('transient backend loss')
            return super().add_table_row(**kwargs)

    backend = FailingBackend()
    table = QTableView(backend=backend, columns=['Name'])
    table.set_rows([('first', ('A',))])
    old_tag = table._row_tags['first']
    backend.fail_once = True
    table.set_rows([('first', ('A',)), ('second', ('B',))])
    assert table.rowValues('second') == ('B',)
    assert table._row_tags['first'] != old_tag
    assert table._row_tags['second'] in backend.config


def test_table_sorted_append_uses_structural_fallback():
    backend = TrackingBackend()
    table = QTableView(backend=backend, columns=['Name'])
    table.set_rows([('a', ('A',)), ('b', ('B',))])
    old_tag = table._row_tags['a']
    table._sort_key = '0'
    table.set_rows([('a', ('A',)), ('b', ('B',)), ('c', ('C',))])
    assert table._row_tags['a'] != old_tag
    assert table.rowValues('c') == ('C',)


def test_list_backend_partial_append_failure_cleans_up_before_rebuild():
    class FailingBackend(TrackingBackend):
        fail_once = False

        def add_selectable(self, **kwargs):
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError('transient backend error')
            return super().add_selectable(**kwargs)

    backend = FailingBackend()
    view = QListView(backend=backend)
    view.setItems([QtListItem(1, 'Old')])
    old_native = view.items[1]
    backend.fail_once = True
    view.setItems([QtListItem(1, 'Old'), QtListItem(2, 'New', checked=True)])
    assert view.items[1] != old_native
    assert 2 in view.checkboxes
    assert view.items[2] in backend.config
    assert view.checkboxes[2] in backend.config
