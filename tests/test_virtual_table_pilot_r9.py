"""Opt-in virtual viewport and large selection regression tests (no native DPG)."""
import pytest

from DearUIQt.modelview import (
    QtItemViewState, QtGridRow, QTableView,
    ReadOnlyTableViewport, compute_virtual_window,
    capture_view_resources,
)
from tests.test_dearuiqt_modelview_r79 import FakeBackend


def test_virtual_window_bounds_and_empty_startup():
    assert compute_virtual_window(0, 24, 0, 480).materialized_rows == 0
    first = compute_virtual_window(100000, 24, 0, 480, overscan=8)
    assert (first.start, first.stop) == (0, 28)
    assert first.trailing_pixels == (100000 - 28) * 24
    mid = compute_virtual_window(100000, 24, 24000, 480, overscan=8)
    assert (mid.start, mid.stop) == (992, 1028)
    last = compute_virtual_window(100000, 24, 10**12, 480, overscan=8)
    assert (last.start, last.stop) == (99972, 100000)
    startup = compute_virtual_window(100000, 24, 0, 0)
    assert startup.materialized_rows == 64
    for invalid in (0, -1, float('inf'), float('nan')):
        with pytest.raises(ValueError):
            compute_virtual_window(10, invalid, 0, 100)
    for value in (float('inf'), float('nan')):
        with pytest.raises(ValueError):
            compute_virtual_window(10, 24, value, 100)


def test_virtual_table_100k_rows_materializes_only_visible_native_page():
    backend = FakeBackend()
    view = QTableView(columns=['Name', 'Value'], backend=backend, multiple=True)
    rows = [QtGridRow(i, (str(i), i)) for i in range(100_000)]
    pilot = ReadOnlyTableViewport(view, rows, row_height=24, overscan=6)
    first = pilot.render(0, 480)
    assert first.materialized_rows <= 32
    assert capture_view_resources(view).tracked_native_rows == first.materialized_rows
    assert capture_view_resources(view).logical_rows == 100_000
    assert len(view._row_tags) < 50
    middle = pilot.render(720_000, 480)
    assert middle.start >= 29_000
    assert capture_view_resources(view).tracked_native_rows == middle.materialized_rows
    assert len(view._row_tags) < 50
    previous_native_ids = dict(view._row_tags)
    assert pilot.render(720_000, 480) == middle
    assert previous_native_ids == view._row_tags  # no new backend allocations
    pilot.detach()
    assert pilot._connection is None
    view.delete()


def test_pilot_remembers_selection_across_windows_and_does_not_emit_on_page():
    backend = FakeBackend()
    view = QTableView(columns=['Name'], backend=backend, multiple=True)
    rows = [QtGridRow(i, (f'row-{i}',)) for i in range(500)]
    pilot = ReadOnlyTableViewport(view, rows, row_height=20)
    changes = []
    pilot.selectionChanged.connect(lambda keys: changes.append(keys))
    pilot.render(0, 200)
    view.setCurrentKey(4)
    assert 4 in pilot.selectedKeys
    assert len(changes) == 1
    pilot.render(4000, 200)
    assert 4 in pilot.selectedKeys
    assert len(changes) == 1
    view.setCurrentKey(201)
    assert {4, 201}.issubset(pilot.selectedKeys)
    pilot.render(0, 200)
    assert 4 in view.selected
    assert len(changes) == 2
    pilot.detach()
    view.delete()


def test_pilot_refuses_sorting_or_editors():
    view = QTableView(columns=['A'], backend=FakeBackend())
    view._sort_key = '0'
    with pytest.raises(ValueError):
        ReadOnlyTableViewport(view, [(1, ('one',))])
    view._sort_key = None
    pilot = ReadOnlyTableViewport(view, [(1, ('one',))])
    view._persistent_editors['test'] = object()
    with pytest.raises(ValueError):
        pilot.render(0, 300)
    view._persistent_editors.clear()
    pilot.detach()
    view.delete()


def test_indexed_selection_navigation_and_duplicate_keys_semantics():
    state = QtItemViewState(multiple=True).replace(range(100_000))
    state.select(90_000)
    key, changed = state.move(1, ctrl=True)
    assert changed and key == 90001 and state.selected == {90000}
    state.move(4, shift=True)
    assert state.selected == set(range(90000, 90006))
    state.replace([2, 2, 1, 3])
    assert state._key_index[2] == 0
    state.select(3)
    state.select(2, shift=True)
    assert state.selected == {2, 1, 3}


def test_resources_memory_snapshots_on_window_change():
    from DearUIQt.modelview import capture_view_memory, compare_view_memory
    view = QTableView(columns=['Name'], backend=FakeBackend())
    rows = [QtGridRow(i, (str(i),)) for i in range(10_000)]
    pilot = ReadOnlyTableViewport(view, rows, row_height=20)
    pilot.render(0, 100)
    initial = capture_view_memory(view, verify_native=True)
    assert initial.resources.logical_rows == 10_000
    assert initial.resources.missing_native_items == 0
    pilot.render(20_000, 200)
    later = capture_view_memory(view, verify_native=True)
    difference = compare_view_memory(initial, later)
    assert later.sample_time_ns >= initial.sample_time_ns
    assert difference.logical_rows == 0
    assert difference.native_rows <= 20
    assert isinstance(difference.native_controls, int)
    if initial.process_rss_bytes is not None and later.process_rss_bytes is not None:
        assert difference.process_rss_bytes == (later.process_rss_bytes - initial.process_rss_bytes)
    pilot.detach()
    view.delete()


def test_viewport_controller_does_not_leak_signal_connections():
    backend = FakeBackend()
    view = QTableView(columns=['A'], backend=backend)
    before = len(view.selectionChanged._slots)
    for _ in range(30):
        pilot = ReadOnlyTableViewport(view, [(1, ('1',))])
        assert len(view.selectionChanged._slots) == before + 1
        pilot.detach()
    assert len(view.selectionChanged._slots) == before
    view.delete()


def test_virtual_rows_change_prunes_stale_selected_keys():
    view = QTableView(columns=['A'], backend=FakeBackend(), multiple=True)
    pilot = ReadOnlyTableViewport(view, [QtGridRow(i, (i,)) for i in range(100)], row_height=20)
    pilot.render(0, 100)
    view.setCurrentKey(1)
    pilot.setRows([QtGridRow(i, (i,)) for i in range(40, 90)])
    assert 1 not in pilot.selectedKeys
    assert pilot.currentKey is None
    pilot.detach()
    view.delete()


def test_no_native_sorting_and_stale_key_pruning_notifications():
    view = QTableView(columns=['A'], backend=FakeBackend(), sortable=True)
    with pytest.raises(ValueError):
        ReadOnlyTableViewport(view, [])
    view.delete()
    view = QTableView(columns=['A'], backend=FakeBackend(), multiple=True)
    pilot = ReadOnlyTableViewport(view, [QtGridRow(i, (i,)) for i in range(20)])
    observed = []
    pilot.selectionChanged.connect(lambda keys: observed.append(keys))
    pilot.render(0, 200)
    view.setCurrentKey(1)
    pilot.setRows([QtGridRow(i, (i,)) for i in range(2, 20)])
    assert observed[-1] == frozenset()
    assert pilot.selectedKeys == frozenset()
    with pytest.raises(ValueError):
        pilot.setRows([QtGridRow(1, (1,)), QtGridRow(1, (2,))])
    pilot.detach()
    view.delete()


def test_index_cache_survives_payload_refresh_and_invalidates_on_reorder():
    state = QtItemViewState(multiple=True).replace(range(10000))
    previous = state._key_index
    state.select(9000)
    state.replace(range(10000))
    assert state._key_index is previous
    assert state.selected == {9000}
    state.replace(range(9999, -1, -1))
    assert state._key_index is not previous
    assert state._key_index[9000] == 999
    assert state.selected == {9000}


def test_virtual_single_selection_replaces_hidden_selected_key():
    view = QTableView(columns=['A'], backend=FakeBackend(), multiple=False)
    pilot = ReadOnlyTableViewport(view, [QtGridRow(i, (i,)) for i in range(100)], row_height=20)
    pilot.render(0, 100)
    view.setCurrentKey(1)
    assert pilot.selectedKeys == {1}
    pilot.render(1000, 100)
    view.setCurrentKey(51)
    assert pilot.selectedKeys == {51}
    pilot.detach()
    view.delete()


def test_virtual_table_rejects_duplicates_before_subscribing():
    view = QTableView(columns=['A'], backend=FakeBackend())
    old_count = len(view.selectionChanged._slots)
    with pytest.raises(ValueError):
        ReadOnlyTableViewport(view, [QtGridRow('x', (1,)), QtGridRow('x', (2,))])
    assert len(view.selectionChanged._slots) == old_count
    assert getattr(view, '_virtual_viewport_controller', None) is None
    view.delete()
