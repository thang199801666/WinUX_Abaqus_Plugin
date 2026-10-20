"""Regression for scroll-range feedback in auto-sized dialog/toolbar containers."""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from DearUIQt.core import QObject
from DearUIQt.layouts import QGridLayout, QVBoxLayout
from DearUIQt.widgets import QFrame, QGroupBox


ROOT = Path(__file__).resolve().parents[1]


def backend_factory():
    backend = Mock()
    backend.add_child_window.side_effect = iter(range(100, 190))
    backend.add_group.side_effect = iter(range(200, 290))
    backend.add_table.side_effect = iter(range(300, 390))
    return backend


@pytest.mark.parametrize('auto_resize,expected', [(True, 0), (False, -1)])
def test_group_box_autosized_child_grid_uses_intrinsic_height(auto_resize, expected):
    backend = backend_factory()
    with patch.object(QGroupBox, 'setTitle', lambda *args: None), patch.object(QFrame, '_refresh_style', lambda *_: None):
        group_box = QGroupBox('Options', backend=backend, auto_resize_y=auto_resize)
        layout = QVBoxLayout(parent=group_box)
        grid = QGridLayout(2, parent=layout, backend=backend)
    assert group_box._vertical_sizing_host
    assert group_box._auto_resize_y is auto_resize
    assert grid.parent is layout
    assert backend.add_table.call_args.kwargs['height'] == expected


def test_fixed_frame_inside_groupbox_still_uses_fill_height():
    backend = backend_factory()
    with patch.object(QFrame, '_refresh_style', lambda *_: None):
        group_box = QGroupBox('Outer', backend=backend, auto_resize_y=True)
        inner = QFrame(parent=group_box, height=200)
        QGridLayout(parent=inner)
    assert backend.add_table.call_args.kwargs['height'] == -1


def test_native_proxy_ancestor_auto_height_resolves_without_python_widget_parent():
    """QtDialog._qt_parent() returns a QObject proxy for raw DPG group tags."""
    backend = backend_factory()
    proxy = QObject()
    proxy.tag = 10
    proxy.backend = backend
    parents = {10: 11, 11: 12, 12: 0}
    configurations = {
        10: {'show': True},       # native group under groupbox
        11: {'show': True},       # another nested group
        12: {'auto_resize_y': True, 'height': 0},
    }
    backend.get_item_configuration.side_effect = lambda tag: configurations[tag]
    backend.get_item_parent.side_effect = lambda tag: parents[tag]
    QGridLayout(parent=proxy, height=-1)
    assert backend.add_table.call_args.kwargs['height'] == 0
    assert backend.get_item_configuration.call_count == 3


def test_native_proxy_fixed_child_frame_terminates_search():
    backend = backend_factory()
    proxy = QObject()
    proxy.tag = 10
    proxy.backend = backend
    parents = {10: 11, 11: 12, 12: 0}
    configurations = {
        10: {'show': True},
        11: {'auto_resize_y': False, 'height': 80},
        12: {'auto_resize_y': True, 'height': 0},
    }
    backend.get_item_configuration.side_effect = lambda tag: configurations[tag]
    backend.get_item_parent.side_effect = lambda tag: parents[tag]
    QGridLayout(parent=proxy)
    assert backend.add_table.call_args.kwargs['height'] == -1
    assert backend.get_item_configuration.call_count == 2


@pytest.mark.parametrize('height', [0, 28, 96])
def test_native_autoheight_does_not_override_explicit_grid_heights(height):
    backend = backend_factory()
    proxy = QObject()
    proxy.tag = 10
    proxy.backend = backend
    backend.get_item_configuration.side_effect = AssertionError('No introspection for explicit heights')
    QGridLayout(parent=proxy, height=height)
    assert backend.add_table.call_args.kwargs['height'] == height
    assert not backend.get_item_configuration.called


def test_dialog_summary_grid_is_content_height():
    source = (ROOT/'DearUIQt/dialogs/qt_dialog.py').read_text()
    summary = source.split('def summary_grid(', 1)[1].split('def labeled_widget(', 1)[0]
    assert 'height=0' in summary


def test_compact_dialog_toolbars_use_natural_height():
    files = {
        'WinUx/dialogs/folder_browser_address.py': ['self._grid = QGridLayout('],
        'WinUx/dialogs/local_folder_form.py': [
            'self._location_grid = self.own_widget(QGridLayout(',
            'self._address_grid = self.own_widget(QGridLayout(',
            'self._search_grid = self.own_widget(QGridLayout(',
        ],
        'WinUx/ui/components/toolbar.py': ['self._search_grid = QGridLayout('],
    }
    for path, snippets in files.items():
        source = (ROOT/path).read_text()
        for snippet in snippets:
            grid = source.split(snippet, 1)[1].split('height=0', 1)[0]
            assert len(grid) < 360, (path, snippet)
            assert 'height=0' in source.split(snippet, 1)[1][:360], (path, snippet)


def test_autosized_table_protection_still_keeps_scrollhost_scrollable():
    source = (ROOT/'WinUx/dialogs/transfer_center_form.py').read_text()
    host = source.split('self._rows_host_frame = QFrame(', 1)[1].split('self.rows_host =', 1)[0]
    assert 'no_scrollbar=False' in host


def test_native_parent_cycle_does_not_hang_or_change_fixed_layout():
    backend = backend_factory()
    parent = QObject()
    parent.tag = 10
    parent.backend = backend
    backend.get_item_configuration.return_value = {'show': True}
    backend.get_item_parent.return_value = 10
    QGridLayout(parent=parent)
    assert backend.add_table.call_args.kwargs['height'] == -1
    assert backend.get_item_parent.call_count == 1


def test_unavailable_native_configuration_uses_old_fill_semantics():
    backend = backend_factory()
    parent = QObject()
    parent.tag = 10
    parent.backend = backend
    backend.get_item_configuration.side_effect = RuntimeError('backend not initialized')
    QGridLayout(parent=parent)
    assert backend.add_table.call_args.kwargs['height'] == -1
