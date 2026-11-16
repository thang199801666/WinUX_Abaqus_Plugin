"""Delayed selector work must not overwrite newer user state."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from DearUIQt.core import Qt
from DearUIQt.modelview.models import QtItemViewState, QtListItem
from WinUx.dialogs.local_folder_form import FolderListView, LocalPathDialog


class SelectorStateStabilityTests(unittest.TestCase):
    def test_delayed_scroll_restore_does_not_rewind_newer_scroll(self):
        for axis, method in (('y', '_restore_table_scroll'), ('x', '_restore_table_horizontal_scroll')):
            with self.subTest(axis=axis):
                view = FolderListView.__new__(FolderListView)
                view._deleted = False
                view._row_generation = 2
                view._details_table = SimpleNamespace(tag='table', _deleted=False)
                view._reset_host_scroll = Mock()
                view.backend = Mock()
                getattr(view.backend, 'get_' + axis + '_scroll').return_value = 430
                getattr(view, method)('table', 120, 2)
                getattr(view.backend, 'set_' + axis + '_scroll').assert_not_called()

    def test_reflow_does_not_reselect_current_or_focus_native_row(self):
        view = FolderListView.__new__(FolderListView)
        view._deleted = False
        view.details_mode = False
        view._values = ['first', 'third']
        view._list_reflow_serial = 0
        view._list_reflow_pending = False
        view._list_flow_rows, view._list_flow_columns = 12, 2
        view._mode_flow_shape = lambda: (10, 3)
        view._state = SimpleNamespace(current='first', selected={'first', 'third'})
        view.items = {'first': 1, 'third': 2}
        view.setItems = Mock()
        view.setCurrentKey = Mock()
        queued = []
        view._after = lambda delay, callback, *args: queued.append((callback, args))
        view.requestListReflow()
        callback, args = queued.pop(0)
        callback(*args)
        view.setItems.assert_called_once_with(['first', 'third'])
        view.setCurrentKey.assert_not_called()
        self.assertEqual(view.selected, {'first', 'third'})

    def test_cells_do_not_allocate_duplicate_pointer_handlers(self):
        view = FolderListView.__new__(FolderListView)
        view._details_table = SimpleNamespace(_deleted=False)
        view._row_generation = 1
        view._visual_hit_bindings = []
        view.backend = Mock()
        with patch('WinUx.dialogs.local_folder_form.QItemInputBinding') as binding:
            view._bind_visual_cell_hit('size-cell', 'third')
            binding.assert_not_called()

    def test_delayed_restore_is_cancelled_even_if_user_scrolled_to_zero(self):
        view = FolderListView.__new__(FolderListView)
        view._deleted = False
        view._row_generation = 2
        view._scroll_restore_revision = 4
        view._details_table = SimpleNamespace(tag='table', _deleted=False)
        view.backend = Mock()
        view.backend.get_y_scroll.return_value = 0
        view._cancel_scroll_restore()  # Wheel, scrollbar press or newer selection.
        view._restore_table_scroll('table', 120, 2, 4)
        view.backend.set_y_scroll.assert_not_called()

    def test_initial_zero_scroll_can_still_be_restored(self):
        view = FolderListView.__new__(FolderListView)
        view._deleted = False
        view._row_generation = 2
        view._scroll_restore_revision = 4
        view._details_table = SimpleNamespace(tag='table', _deleted=False)
        view._reset_host_scroll = Mock()
        view.backend = Mock()
        view.backend.get_y_scroll.return_value = 0
        view._restore_table_scroll('table', 120, 2, 4)
        view.backend.set_y_scroll.assert_called_once_with('table', 120.0)

    def test_scan_result_does_not_reselect_pending_item_after_user_change(self):
        for revision, should_select in ((1, True), (2, False)):
            with self.subTest(revision=revision):
                listing = SimpleNamespace(_selection_revision=revision,
                    items={'first': 1, 'third': 3}, setCurrentKey=Mock())
                dialog = SimpleNamespace(
                    winfo_exists=lambda: True, _generation=3, _current_path='root',
                    listbox=listing, _select_after_load='first', _select_after_load_revision=1,
                    _rename_after_load='first', _filter_entries=Mock(),
                    view=SimpleNamespace(after=Mock()), _begin_folder_rename=Mock())
                LocalPathDialog._apply_entries(dialog, 3, 'root', [], None,
                                               selection_revision=1)
                if should_select:
                    listing.setCurrentKey.assert_called_once_with('first', select=True)
                else:
                    listing.setCurrentKey.assert_not_called()
                    dialog.view.after.assert_not_called()
                    self.assertIsNone(dialog._rename_after_load)
                self.assertIsNone(dialog._select_after_load)
                self.assertIsNone(dialog._select_after_load_revision)

    def test_deferred_select_token_cannot_reclaim_focus_after_new_user_selection(self):
        state = QtItemViewState(multiple=False)
        state.replace(['winux_runtime', 'tests'])
        state.select('tests')
        listing = SimpleNamespace(
            _selection_revision=12, _scroll_restore_revision=20, _row_generation=4,
            _state=state, items={'winux_runtime': 1, 'tests': 2},
            current='tests', selected={'tests'},
            verticalScrollValue=lambda: 210.0, horizontalScrollValue=lambda: 0.0,
            setVerticalScrollValue=Mock(), setHorizontalScrollValue=Mock(),
            _cancel_scroll_restore=Mock(), _full_visual_sync=False,
            _sync_selection_visuals=Mock(), _sync_model_selection=Mock(),
            _details_table=SimpleNamespace(tag='table', _deleted=False),
            setCurrentKey=Mock(), _restore_table_scroll=Mock(),
            _restore_table_horizontal_scroll=Mock(),
        )
        dialog = SimpleNamespace(
            winfo_exists=lambda: True, _generation=8, _current_path='root',
            listbox=listing, _select_after_load='winux_runtime',
            _select_after_load_revision=11, _rename_after_load=None,
            _filter_entries=Mock(), view=SimpleNamespace(after=Mock()),
            _begin_folder_rename=Mock())
        LocalPathDialog._apply_entries(
            dialog, 8, 'root', [], None, selection_revision=12, scroll_revision=20)
        listing.setCurrentKey.assert_not_called()
        self.assertEqual(listing._state.current, 'tests')
        self.assertEqual(listing._state.selected, {'tests'})
        listing.setVerticalScrollValue.assert_called_with(210.0)


    def test_reorder_details_never_invents_first_current_row(self):
        view = FolderListView.__new__(FolderListView)
        view.details_mode = True
        view._rendered_details_mode = True
        view._values = [QtListItem('b', 'b'), QtListItem('a', 'a')]
        view._state = QtItemViewState(multiple=False)
        view._state.replace(['b', 'a'])
        view._state.current = None
        view._state.anchor = None
        view.backend = Mock()
        row_b, row_a = object(), object()
        table = SimpleNamespace(_deleted=False, _row_tags=[row_b, row_a],
                                _items={}, _native_items={}, _cell_widgets={},
                                columnCount=lambda: 4, _reindex_cell_widget_keys=Mock(), tag='table')
        view._details_table = table
        view._row_index = {}
        view._visual_positions = {}
        view._visual_keys = {}
        view._full_visual_sync = False
        view._sync_selection_visuals = Mock()
        view._sync_details_header_geometry = Mock()
        view._last_click_key = None
        view._last_click_frame = None
        self.assertTrue(view.reorderDetails([QtListItem('a', 'a'), QtListItem('b', 'b')]))
        self.assertIsNone(view.current)
        self.assertIsNone(view.anchor)

    def test_delayed_scan_preserves_live_selection_and_scroll(self):
        state = QtItemViewState(multiple=False)
        state.replace(['first', 'second', 'third'])
        state.select('third')
        listing = SimpleNamespace(
            _selection_revision=2, _scroll_restore_revision=5, _row_generation=7,
            _state=state, items={'first': 1, 'second': 2, 'third': 3},
            current='third', selected={'third'},
            verticalScrollValue=lambda: 180.0, horizontalScrollValue=lambda: 0.0,
            setVerticalScrollValue=Mock(), setHorizontalScrollValue=Mock(),
            _full_visual_sync=False, _sync_selection_visuals=Mock(), _sync_model_selection=Mock(),
            _details_table=SimpleNamespace(tag='table', _deleted=False),
            setCurrentKey=Mock(),
        )
        def filter_entries():
            # Simulate a late structural refresh trying to revert to row zero.
            listing._state.current = 'first'
            listing._state.anchor = 'first'
            listing._state.selected = {'first'}
            listing.current = 'first'
            listing.selected = {'first'}
        dialog = SimpleNamespace(
            winfo_exists=lambda: True, _generation=3, _current_path='root',
            listbox=listing, _select_after_load=None, _select_after_load_revision=None, _rename_after_load=None,
            _filter_entries=filter_entries, view=SimpleNamespace(after=Mock()),
            _begin_folder_rename=Mock())
        LocalPathDialog._apply_entries(
            dialog, 3, 'root', [], None, selection_revision=1, scroll_revision=4)
        self.assertEqual(listing._state.current, 'third')
        self.assertEqual(listing._state.selected, {'third'})
        listing.setVerticalScrollValue.assert_called_with(180.0)

    def test_refresh_started_after_user_interaction_still_preserves_live_state(self):
        state = QtItemViewState(multiple=False)
        state.replace(['old', 'new'])
        state.select('new')
        listing = SimpleNamespace(
            _selection_revision=7, _scroll_restore_revision=9, _row_generation=3,
            _state=state, items={'old': 1, 'new': 2}, current='new', selected={'new'},
            verticalScrollValue=lambda: 240.0, horizontalScrollValue=lambda: 0.0,
            setVerticalScrollValue=Mock(), setHorizontalScrollValue=Mock(),
            _cancel_scroll_restore=Mock(), _full_visual_sync=False,
            _sync_selection_visuals=Mock(), _sync_model_selection=Mock(),
            _details_table=SimpleNamespace(tag='table', _deleted=False),
            setCurrentKey=Mock(), _restore_table_scroll=Mock(),
            _restore_table_horizontal_scroll=Mock(),
        )
        def filter_entries():
            # Simulate a native rebuild reviving the previous current row and
            # resetting the viewport, even though the scan began after the
            # user's interaction and therefore captured the same revisions.
            listing._state.current = 'old'
            listing._state.anchor = 'old'
            listing._state.selected = {'old'}
            listing.current = 'old'
            listing.selected = {'old'}
        dialog = SimpleNamespace(
            winfo_exists=lambda: True, _generation=4, _current_path='root',
            listbox=listing, _select_after_load=None, _select_after_load_revision=None, _rename_after_load=None,
            _filter_entries=filter_entries, view=SimpleNamespace(after=Mock()),
            _begin_folder_rename=Mock())
        LocalPathDialog._apply_entries(
            dialog, 4, 'root', [], None, selection_revision=7, scroll_revision=9)
        self.assertEqual(listing._state.current, 'new')
        self.assertEqual(listing._state.selected, {'new'})
        listing.setVerticalScrollValue.assert_called_with(240.0)
        listing._cancel_scroll_restore.assert_called_once()
        listing.setCurrentKey.assert_not_called()


    def test_legacy_global_press_cannot_replay_qt_owned_press(self):
        view = FolderListView.__new__(FolderListView)
        view._deleted = False
        view.items = {'first': 1, 'third': 3}
        view._qt_pointer_registered = True
        view._state = SimpleNamespace(current='third', selected={'third'})
        view._qt_bridge_click = ('third', 9, 0)
        view._reset_host_scroll = Mock()
        self.assertFalse(view._row_pointer_clicked())
        self.assertEqual(view.current, 'third')
        self.assertEqual(view.selected, {'third'})
        self.assertEqual(view._qt_bridge_click, ('third', 9, 0))

    def test_standalone_host_uses_real_renderer_frame_counter(self):
        view = FolderListView.__new__(FolderListView)
        view.backend = Mock()
        view.backend.get_frame_count.return_value = 42
        with patch('WinUx.dialogs.local_folder_form.QApplication.instance', return_value=None):
            self.assertEqual(view._input_frame(), 42)
            view._arm_native_click_bridge('third')
            self.assertEqual(view._qt_bridge_click[:2], ('third', 42))

    def test_pointer_transaction_finishes_after_a_real_release_frame(self):
        dialog = LocalPathDialog.__new__(LocalPathDialog)
        dialog._generation = 1
        dialog.listbox = SimpleNamespace(_input_frame=Mock(side_effect=[40, 41, 42]))
        with patch('WinUx.dialogs.local_folder_form.os', SimpleNamespace(name='portable')), \
                patch('WinUx.dialogs.local_folder_form.QCursor.buttons', return_value=Qt.NoButton):
            transaction = dialog._new_pointer_transaction()
            self.assertFalse(dialog._pointer_transaction_finished(transaction))
            self.assertTrue(dialog._pointer_transaction_finished(transaction))

    def test_superseded_scan_stops_before_probing_more_entries(self):
        first, second = Mock(), Mock()
        first.name, first.path = 'first', 'root/first'
        first.is_dir.return_value = True
        first.stat.return_value = SimpleNamespace(st_file_attributes=0, st_mtime=0, st_size=0)
        dialog = SimpleNamespace(_generation=0, _current_path='root', _show_hidden_items=False,
            winfo_exists=lambda: True, _set_status=Mock(), _include_entry=lambda entry, is_dir: True,
            _apply_entries=Mock(), runAsync=lambda worker, on_result: on_result(worker()))

        def entries():
            yield first
            dialog._generation += 1
            yield second

        manager = Mock()
        manager.__enter__ = Mock(return_value=entries())
        manager.__exit__ = Mock(return_value=False)
        with patch('WinUx.dialogs.local_folder_form.os.scandir', return_value=manager), \
                patch('WinUx.dialogs.local_folder_form.file_type_name', return_value='Folder'):
            LocalPathDialog._refresh(dialog)
        first.is_dir.assert_called_once()
        second.is_dir.assert_not_called()


if __name__ == '__main__':
    unittest.main()

class SelectionStateNoImplicitFirstCurrentTests(unittest.TestCase):
    def test_replace_does_not_invent_first_current_when_none(self):
        state = QtItemViewState(multiple=False)
        state.replace(['first', 'second'])
        self.assertIsNone(state.current)
        self.assertIsNone(state.anchor)

    def test_replace_drops_removed_current_to_none_not_first(self):
        state = QtItemViewState(multiple=False)
        state.replace(['old', 'first', 'second'])
        state.current = 'old'
        state.anchor = 'old'
        state.selected = {'old'}
        state.replace(['first', 'second'])
        self.assertIsNone(state.current)
        self.assertIsNone(state.anchor)
        self.assertEqual(state.selected, set())
