"""Headless validation of the opt-in native-scrollbar-to-logical-row bridge."""
import pytest

from DearUIQt.core import Qt
from DearUIQt.modelview import (QTableView, QtGridRow, ReadOnlyTableViewport,
                                LogicalTableScrollBridge, capture_view_resources)
from DearUIQt.widgets import QScrollBar
from tests.test_dearuiqt_modelview_r79 import FakeBackend


class SliderBackend(FakeBackend):
    def add_vslider_int(self, **kwargs):
        return self._new(**kwargs)


def prepare(count=100_000, viewport_height=480, row_height=24):
    backend = SliderBackend()
    view = QTableView(columns=['Name'], backend=backend, multiple=True)
    slider = QScrollBar(Qt.Vertical, backend=backend)
    rows = [QtGridRow(i, (str(i),)) for i in range(count)]
    pilot = ReadOnlyTableViewport(view, rows, row_height=row_height, overscan=5)
    bridge = LogicalTableScrollBridge(pilot, slider, viewport_height=viewport_height)
    return backend, view, slider, pilot, bridge


def cleanup(view, slider, pilot, bridge):
    bridge.detach()
    pilot.detach()
    slider.delete()
    view.delete()


def test_bridge_maps_100k_rows_to_native_slider_with_bounded_allocation():
    backend, view, slider, pilot, bridge = prepare()
    assert bridge.maximumTopRow == 99980
    assert slider.maximum() == 99980
    assert slider.pageStep() == 20
    assert pilot.window.start == 0
    assert capture_view_resources(view).tracked_native_rows <= 40
    slider.setValue(50000)
    assert bridge.topRow == 50000
    assert pilot.window.start <= 50000 < pilot.window.stop
    assert capture_view_resources(view).tracked_native_rows <= 40
    assert slider.value() == 50000
    cleanup(view, slider, pilot, bridge)


def test_bridge_clamps_to_last_partial_page_and_resizes():
    backend, view, slider, pilot, bridge = prepare(count=100, viewport_height=95, row_height=20)
    assert bridge.maximumTopRow == 96
    slider.setValue(96)
    assert pilot.window.stop == 100
    assert pilot.window.start <= 95
    bridge.setViewportHeight(300)
    assert bridge.maximumTopRow == 85
    assert bridge.topRow == 85
    assert pilot.window.stop == 100
    bridge.setViewportHeight(5000)
    assert bridge.maximumTopRow == 0
    assert bridge.topRow == 0
    cleanup(view, slider, pilot, bridge)


def test_scroll_to_row_keyboard_alignment_and_noop_doesnt_allocate():
    backend, view, slider, pilot, bridge = prepare(count=2000, viewport_height=200, row_height=20)
    bridge.scrollToRow(250, alignment='center')
    assert bridge.topRow == 245
    assert 250 in range(pilot.window.start, pilot.window.stop)
    before = dict(view._row_tags)
    bridge.scrollToRow(250, alignment='nearest')
    assert view._row_tags == before
    bridge.scrollToRow(0, alignment='start')
    assert bridge.topRow == 0
    bridge.scrollToRow(1999, alignment='end')
    assert bridge.topRow == 1990
    with pytest.raises(ValueError):
        bridge.scrollToRow(0, alignment='middle')
    cleanup(view, slider, pilot, bridge)


def test_wheel_fractional_deltas_and_invalid_inputs():
    backend, view, slider, pilot, bridge = prepare(count=1000, viewport_height=200, row_height=20)
    bridge.scrollToRow(100, alignment='start')
    bridge.wheel(-40)
    bridge.wheel(-40)
    assert bridge.topRow == 100
    bridge.wheel(-40)
    assert bridge.topRow == 103
    bridge.wheel(120)
    assert bridge.topRow == 100
    with pytest.raises(ValueError):
        bridge.wheel(float('inf'))
    with pytest.raises(ValueError):
        bridge.setViewportHeight(float('nan'))
    assert bridge.topRow == 100
    cleanup(view, slider, pilot, bridge)


def test_bridge_refresh_data_clamps_position_and_preserves_selection():
    backend, view, slider, pilot, bridge = prepare(count=200, viewport_height=200, row_height=20)
    bridge.scrollToRow(150, alignment='start')
    view.setCurrentKey(151)
    assert 151 in pilot.selectedKeys
    bridge.refreshRows([QtGridRow(i, (str(i),)) for i in range(180)])
    assert bridge.topRow == 150
    assert 151 in pilot.selectedKeys
    bridge.refreshRows([QtGridRow(i, (str(i),)) for i in range(30)])
    assert bridge.topRow == 20
    assert 151 not in pilot.selectedKeys
    assert pilot.window.stop == 30
    cleanup(view, slider, pilot, bridge)


def test_owning_view_not_modified_after_bridge_detach():
    backend, view, slider, pilot, bridge = prepare(count=400, viewport_height=200, row_height=20)
    before = len(slider.valueChanged._slots)
    assert before >= 1
    bridge.detach()
    assert len(slider.valueChanged._slots) == before - 1
    old_window = pilot.window
    slider.setValue(50)
    assert pilot.window is old_window
    with pytest.raises(RuntimeError):
        bridge.scrollByRows(1)
    pilot.detach()
    slider.delete()
    view.delete()


def test_multiple_bridges_not_add_handlers_to_views_or_change_normal_path():
    backend = SliderBackend()
    view = QTableView(columns=['A'], backend=backend)
    rows = [QtGridRow(i, (i,)) for i in range(100)]
    pilot = ReadOnlyTableViewport(view, rows)
    slider = QScrollBar(Qt.Vertical, backend=backend)
    baseline = len(slider.valueChanged._slots)
    for _ in range(40):
        bridge = LogicalTableScrollBridge(pilot, slider, viewport_height=150)
        bridge.scrollByRows(2)
        bridge.detach()
        assert len(slider.valueChanged._slots) == baseline
    pilot.detach()
    view.set_rows(rows[:10])
    assert len(view.rows) == 10
    slider.delete()
    view.delete()


def test_invalid_bridge_arguments_leave_source_unmodified():
    backend = SliderBackend()
    view = QTableView(columns=['A'], backend=backend)
    pilot = ReadOnlyTableViewport(view, [QtGridRow(1, ('a',))])
    slider = QScrollBar(Qt.Vertical, backend=backend)
    for height in (-1, float('inf'), float('nan')):
        with pytest.raises(ValueError):
            LogicalTableScrollBridge(pilot, slider, viewport_height=height)
    assert len(slider.valueChanged._slots) == 0
    pilot.detach()
    slider.delete()
    view.delete()


def test_view_deletion_auto_detaches_pilot_and_scrollbar_bridge():
    backend, view, slider, pilot, bridge = prepare(count=100, viewport_height=200, row_height=20)
    connection_count = len(slider.valueChanged._slots)
    view.delete()
    assert pilot.view is None
    assert bridge.viewport is None
    assert len(slider.valueChanged._slots) == connection_count - 1
    slider.setValue(5)  # must never reach deleted native table
    slider.delete()


def test_detaching_pilot_auto_detaches_scrollbar_bridge():
    backend, view, slider, pilot, bridge = prepare(count=100, viewport_height=200, row_height=20)
    pilot.detach()
    assert bridge.viewport is None
    assert pilot._logical_scroll_bridge is None
    slider.setValue(5)
    with pytest.raises(RuntimeError):
        bridge.scrollToRow(20)
    view.delete()
    slider.delete()


def test_one_scrollbar_bridge_per_virtual_table():
    backend, view, slider, pilot, bridge = prepare(count=100, viewport_height=200, row_height=20)
    with pytest.raises(RuntimeError):
        LogicalTableScrollBridge(pilot, slider, viewport_height=200)
    cleanup(view, slider, pilot, bridge)


def test_native_slider_callback_is_reflected_in_logical_page():
    backend, view, slider, pilot, bridge = prepare(count=1000, viewport_height=200, row_height=20)
    # Real Dear PyGui applies native slider value before invoking callback.
    backend.set_value(slider.tag, 250)
    slider._changed(slider.tag, 250)
    assert bridge.topRow == 250
    assert pilot.window.start <= 250 < pilot.window.stop
    cleanup(view, slider, pilot, bridge)
