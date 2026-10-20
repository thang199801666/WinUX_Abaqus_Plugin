"""r5: unchanged/repolled model/view rows never require native reconstruction."""

import pytest

from DearUIQt.modelview import QListView, QTableView
from DearUIQt.modelview.models import QtGridRow, QtListItem
from tests.test_dearuiqt_list_render_cache_r4 import CountingBackend


class TrackingBackend(CountingBackend):
    def __init__(self):
        super().__init__()
        self.row_adds = 0
        self.config_calls = []
        self.highlights = []
        self.scrolls = {}

    def add_table_row(self, **kwargs):
        self.row_adds += 1
        return super().add_table_row(**kwargs)

    def configure_item(self, tag, **kwargs):
        self.config_calls.append((tag, kwargs))
        return super().configure_item(tag, **kwargs)

    def get_y_scroll(self, tag):
        return self.scrolls.get(tag, 0.)

    def set_y_scroll(self, tag, value):
        self.scrolls[tag] = float(value)

    def highlight_table_row(self, tag, row, color):
        self.highlights.append((row, color))

    def unhighlight_table_row(self, tag, row):
        self.highlights.append((row, None))


@pytest.fixture(autouse=True)
def mock_themes(monkeypatch):
    monkeypatch.setattr('DearUIQt.modelview.table.qt_item_view_theme', lambda *_: 'view')
    monkeypatch.setattr('DearUIQt.modelview.table.qt_item_row_theme', lambda *_, **__: 'row')
    monkeypatch.setattr('DearUIQt.modelview.table.qt_item_text_theme', lambda *_, **__: 'text')
    monkeypatch.setattr('DearUIQt.modelview.list.qt_item_row_theme', lambda *_, **__: 'row')
    monkeypatch.setattr('DearUIQt.modelview.list.qt_check_list_row_theme', lambda *_, **__: 'check')


def test_table_poll_keeps_native_ids_and_does_zero_renderer_updates():
    b = TrackingBackend()
    view = QTableView(backend=b, columns=['Name', 'Value'])
    view.set_rows([QtGridRow(i, (f'row {i}', i), data={'revision': 0}) for i in range(900)])
    view.setCurrentKey(500, select=True)
    b.set_y_scroll(view.tag, 2100)
    native_rows = dict(view._row_tags)
    selectable = dict(view.items)
    counters = (b.row_adds, b.deletes, b.value_writes, len(b.config_calls))
    view.set_rows([QtGridRow(i, (f'row {i}', i), data={'revision': 1}) for i in range(900)])
    assert counters == (b.row_adds, b.deletes, b.value_writes, len(b.config_calls))
    assert b.get_y_scroll(view.tag) == 2100
    assert view.current == 500 and view.selected == {500}
    assert view._row_tags == native_rows and view.items == selectable
    assert view.rowData(200) == {'revision': 1}


def test_table_updates_only_changed_cells_and_not_selectable_selection_state():
    b = TrackingBackend()
    view = QTableView(backend=b, columns=['Name', 'Value'])
    view.set_rows([('a', ('First', '1')), ('b', ('Second', '2'))])
    selectable = view.items['a']
    cell = view._cell_native_items['b'][1]
    old_selected = b.get_value(selectable)
    prior = b.value_writes
    view.set_rows([('a', ('Edited', '1')), ('b', ('Second', '42'))])
    assert b.config[selectable]['label'] == 'Edited'
    assert b.get_value(selectable) == old_selected
    assert b.values[cell] == '42'
    assert b.value_writes == prior + 1
    assert len(view._row_tags) == 2


def test_table_rebuilds_if_order_or_column_shape_changes():
    b = TrackingBackend()
    view = QTableView(backend=b, columns=['Name', 'Value'])
    view.set_rows([('a', ('First', '1')), ('b', ('Second', '2'))])
    before = dict(view._row_tags)
    view.set_rows([('b', ('Second', '2')), ('a', ('First', '1'))])
    assert view._row_tags['a'] != before['a']
    before = dict(view._row_tags)
    view.set_rows([('b', ('Second',)), ('a', ('First', '1'))])
    assert view._row_tags['a'] != before['a']


def test_table_metadata_and_row_state_refresh_without_rebuild():
    b = TrackingBackend()
    view = QTableView(backend=b, columns=['Name', 'Value'])
    color = (220, 230, 255, 255)
    view.set_rows([QtGridRow('a', ('Name', '0'), enabled=True, background=color)])
    row = view._row_tags['a']
    view.set_rows([QtGridRow('a', ('Name', '0'), enabled=False, background=None)])
    assert view._row_tags['a'] == row
    assert b.config[view.items['a']]['enabled'] is False
    assert (0, None) in b.highlights
    assert view.row_enabled['a'] is False


def test_list_text_and_enabled_state_changes_keep_rows_and_checkboxes():
    b = TrackingBackend()
    view = QListView(backend=b)
    view.setItems([QtListItem(1, 'Alpha', checked=True), QtListItem(2, 'Beta')])
    old_items = dict(view.items)
    old_checkbox = view.checkboxes[1]
    prior_adds = b.adds
    view.setItems([QtListItem(1, 'One', checked=True, enabled=False), QtListItem(2, 'Two')])
    assert view.items == old_items
    assert view.checkboxes[1] == old_checkbox
    assert b.adds == prior_adds
    assert b.config[old_items[1]]['label'] == 'One'
    assert b.config[old_checkbox]['enabled'] is False
    assert b.config[old_items[2]]['label'] == 'Two'
    # A check-value change retains rows and native checkbox identities.
    view.setItems([QtListItem(1, 'One', checked=False, enabled=False), QtListItem(2, 'Two')])
    assert view.items[1] == old_items[1]
    assert view.checkboxes[1] == old_checkbox
    assert b.get_value(old_checkbox) is False
    # Removing the check indicator changes the row shape and must rebuild.
    view.setItems([QtListItem(1, 'One', checked=None, enabled=False), QtListItem(2, 'Two')])
    assert view.items[1] != old_items[1]


def test_model_first_column_change_preserves_selected_boolean():
    from tests.test_dearuiqt_modelview_r79 import make_model
    b = TrackingBackend()
    view = QTableView(backend=b)
    model = make_model()
    view.setModel(model)
    view.setCurrentKey(0, select=True)
    selected_tag = view.items[0]
    before = b.get_value(selected_tag)
    model.setData(model.index(0, 0), 'Edited title')
    assert b.config[selected_tag]['label'] == 'Edited title'
    assert b.get_value(selected_tag) == before
    assert view.rows[0][1][0] == 'Edited title'
