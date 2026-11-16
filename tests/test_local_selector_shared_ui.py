"""Shared scroller and single/multiple selector contracts on rendered widgets.

Run: abaqus python tests/test_local_selector_shared_ui.py
No desktop pointer movement is required.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends.shared_scrollers import _overlays
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.local_folder_form import LocalFolderDialog
from WinUx.dialogs.local_file_form import LocalFileDialog
from WinUx.ui.file_dialog import FileSelector
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='selector-shared-', dir=temp) as directory, \
            patch.dict(os.environ, {'APPDATA': directory}):
        root = Path(directory)
        for index in range(35):
            (root / ('folder %02d' % index)).mkdir()
            (root / ('model %02d.inp' % index)).write_text('test')
        (root / 'other.txt').write_text('test')
        (root / '.hidden.inp').write_text('test')
        view = WinUXView({key: lambda *args, **kwargs: None for key in REQUIRED_CALLBACK_KEYS})
        backend = view._gui_runtime.backend
        dialog = None

        def pump(count=12):
            for _ in range(count):
                view.update()
                time.sleep(.01)

        try:
            view._gui_runtime.show()
            for cls in (LocalFolderDialog, LocalFileDialog):
                for multiple in (False, True):
                    results = []
                    kwargs = {'extensions': ('inp',)} if cls is LocalFileDialog else {}
                    dialog = cls(view, directory, results.append, multiple=multiple, **kwargs)
                    dialog.show()
                    pump(50)
                    listing = dialog.listbox
                    table = listing._details_table.tag
                    entries = _overlays[id(backend)]
                    assert table in entries, ('No shared table scroller', cls.__name__, entries)
                    assert listing.tag not in entries, 'Outer list acquired a second scroll owner'
                    overlay = entries[table]
                    assert overlay.viewport_item == listing.tag
                    assert overlay.target_item == table
                    assert dialog.file_type is not None and 'filter' in dialog._form_labels
                    assert all(not Path(item.key).name.startswith('.') for item in listing._values)
                    if cls is LocalFileDialog:
                        assert str(root / 'other.txt') not in listing.items
                        assert str(root / 'model 00.inp') in listing.items
                    else:
                        assert all(Path(item.key).is_dir() for item in listing._values)
                    state = backend.get_item_state(overlay._hits['v'])
                    expected = overlay._last_axes['v']['hit']
                    assert all(abs(a - b) <= 1 for a, b in zip(
                        (*state['rect_min'], *state['rect_max']), expected))
                    # Drive the actual common scroller interaction model with
                    # deterministic input, leaving the user's mouse untouched.
                    down = [False]
                    cap = overlay._last_axes['v']['end_cap']
                    point = ((cap[0] + cap[2]) / 2, (cap[1] + cap[3]) / 2)
                    with patch.object(overlay, '_pointer', return_value=point), \
                            patch.object(overlay, '_left_button_down', side_effect=lambda: down[0]), \
                            patch.object(overlay, '_foreground_input_blocked', return_value=False), \
                            patch.object(backend, 'is_item_hovered', return_value=True):
                        pump(15)
                        down[0] = True
                        pump(3)
                        down[0] = False
                        pump(3)
                    assert backend.get_y_scroll(table) > 0, 'Shared arrow did not scroll table'
                    assert backend.get_y_scroll(listing.tag) == 0, 'Host stole table scrolling'
                    backend.set_y_scroll(table, 0)
                    pump()

                    # Route real item-view selection logic with Ctrl/Shift,
                    # including directory navigation rows in the file browser.
                    kind = dialog.selection_options.kind
                    keys = [item.key for item in listing._values
                            if dialog._entry_is_dirs[item.key] == (kind == 'folder')]

                    def click(key, modifier=None):
                        listing._qt_bridge_click = None
                        with patch.object(backend, 'is_key_down', side_effect=lambda code: code == modifier):
                            assert listing._route_pointer_key(key)
                        pump(2)

                    click(keys[0])
                    click(keys[2], backend.mvKey_LControl)
                    if multiple:
                        assert listing.selected == {keys[0], keys[2]}
                        click(keys[4], backend.mvKey_LShift)
                        expected_keys = keys[2:5]
                        assert listing.selected == set(expected_keys), listing.selected
                        # Ctrl-toggle the current key: selectionChanged must
                        # update the editor even though current is unchanged.
                        click(keys[4], backend.mvKey_LControl)
                        expected_keys = keys[2:4]
                        assert listing.selected == set(expected_keys)
                    else:
                        expected_keys = [keys[2]]
                        assert listing.selected == set(expected_keys)
                    result = dialog.selection_options.resolve(
                        directory, dialog._folder_edit_control.text())
                    assert result == (expected_keys if multiple else expected_keys[0]), result
                    if multiple and cls is LocalFileDialog:
                        folder = str(root / 'folder 00')
                        click(folder, backend.mvKey_LControl)
                        assert listing.selected == set(expected_keys) | {folder}
                        assert dialog.selection_options.resolve(
                            directory, dialog._folder_edit_control.text()) == expected_keys
                        click(folder, backend.mvKey_LControl)
                        assert listing.selected == set(expected_keys)

                    # Sorting must retain the same common scroller and choices.
                    dialog._sort_entries([(0, -1)])
                    pump()
                    assert listing.selected == set(expected_keys), (
                        cls.__name__, multiple, listing.selected, expected_keys,
                        'generation', listing._row_generation, 'result', results)
                    assert entries[listing._details_table.tag] is overlay
                    if multiple:
                        # List mode owns horizontal scrolling; the common
                        # scroller must follow the replacement table, without
                        # reviving the disabled outer scroll surface.
                        dialog._change_view('List')
                        pump()
                        table = listing._details_table.tag
                        horizontal = entries[table]
                        assert horizontal.horizontal and not horizontal.vertical
                        assert 'h' in horizontal._last_axes
                        assert listing.selected == set(expected_keys)
                        dialog._change_view('Details')
                        pump()
                        table = listing._details_table.tag
                        assert entries[table].vertical
                        assert listing.selected == set(expected_keys)
                    result = dialog.selection_options.resolve(directory, dialog._folder_edit_control.text())
                    dialog._select_folder()
                    assert results == [result], results
                    dialog = None
                    pump()
                    assert table not in entries, 'Destroyed selector retained its shared scroller'
                    print('PASS:', cls.__name__, 'multi' if multiple else 'single',
                          'shared scroller, filtering, Ctrl/Shift, acceptance and cleanup', flush=True)

            results = []
            dialog = LocalFileDialog(view, directory, results.append, save=True,
                                     extensions=('inp',), default_filename='new model')
            dialog.show()
            pump(50)
            assert dialog._folder_edit_control.text() == 'new model'
            # Selecting/renaming a navigation folder must preserve Save's name.
            folder = str(root / 'folder 00')
            dialog.listbox.setCurrentKey(folder, select=True)
            assert dialog._folder_edit_control.text() == 'new model'
            dialog._select_folder()
            assert results == [str(root / 'new model.inp')]
            dialog = None
            pump()

            results = []
            dialog = LocalFileDialog(view, directory, results.append, save=True,
                extensions=('inp',), default_filename='model 00.inp', show_hidden=True)
            dialog.show()
            pump(50)
            assert str(root / '.hidden.inp') in dialog.listbox.items
            dialog._select_folder()
            assert not results and dialog.winfo_exists(), 'Overwrite was not confirmed'
            dialog._select_folder()
            assert results == [str(root / 'model 00.inp')]
            dialog = None
            pump()
            print('PASS: Save default filename, folder navigation, hidden option, extension and overwrite confirmation', flush=True)

            # Exercise the public facade and real in-process adapters as well
            # as the underlying forms (floating payloads have unit coverage).
            for directory_mode in (False, True):
                results = []
                selector = FileSelector(view=view, accepted=results.append,
                    initial=directory, directory=directory_mode, multiple=True,
                    extensions=('inp',), title='Shared selector API')
                with patch.object(view, 'use_native_file_selectors', False, create=True):
                    selector.open()
                dialog = selector.dialog
                pump(50)
                assert dialog.multiple and dialog.dialog_title == 'Shared selector API'
                name = 'folder 00' if directory_mode else 'model 00.inp'
                path = str(root / name)
                dialog.listbox.setCurrentKey(path, select=True)
                dialog._select_folder()
                assert results == [[path]]
                dialog = None
                pump()
            print('PASS: public FileSelector multi-file/multi-folder API through real in-process adapters', flush=True)
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
