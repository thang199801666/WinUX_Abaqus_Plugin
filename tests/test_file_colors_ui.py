"""Real Local/Server filename colors, selection and live preference changes."""
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import time
from dataclasses import replace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.models.items import FileItem
from WinUx.ui.components.file_colors import FILE_COLORS
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None
        def pump(count=8):
            for _ in range(count):
                view.update()
                time.sleep(.01)
        def color(listing, index, key='name'):
            row = listing._row_for_index(index)
            return tuple(round(v * 255) for v in dpg.get_item_configuration(row['texts'][key])['color'])
        try:
            view._gui_runtime.show()
            view.apply_general_preferences({'show_hidden_files': True, 'file_colors': True})
            for panel in view.panels:
                folder = PurePosixPath('/colors') if panel.panel_id == 'server' else Path(profile)
                cases = [('folder', True, {}, 'directory'),
                         ('link', False, {'is_symlink': True}, 'symlink'),
                         ('run.sh', False, {'mode': 0o100755}, 'executable'),
                         ('archive.zip', False, {}, 'archive'),
                         ('image.png', False, {}, 'image'),
                         ('.hidden', False, {'is_hidden': True}, 'hidden'),
                         ('plain.inp', False, {}, None)]
                sources = [FileItem(name, folder / name, directory, 42, 100, **metadata)
                           for name, directory, metadata, _ in cases]
                expected = {name: role for name, _, _, role in cases}
                panel.display(folder, sources)
                listing = panel.listview
                listing.select_indices([])
                pump()
                for index, row in enumerate(listing.items):
                    role = expected[row.name]
                    assert color(listing, index) == (FILE_COLORS[role] if role else listing.theme_config['text']), (panel.panel_id, row.name, color(listing, index), role, listing.name_color_provider, listing.selected, listing._row_for_index(index).get('visual_text_color'))
                    assert color(listing, index, 'size') == listing.theme_config['text']
                index = next(i for i, row in enumerate(listing.items) if row.name == 'image.png')
                listing.select_indices([index])
                for focused in (False, True):
                    listing._has_focus = focused
                    listing.refresh_row_visuals()
                    pump(2)
                    expected_color = listing.theme_config['selected_text' if listing._has_focus else 'inactive_selected_text']
                    assert color(listing, index) == expected_color, (focused, color(listing, index), expected_color, listing.selected)
                panel.set_file_colors(False)
                listing.select_indices([])
                pump()
                assert all(color(listing, i) == listing.theme_config['text'] for i in range(len(listing.items)))
                panel.set_file_colors(True)
                pump()
                assert color(listing, index) == FILE_COLORS['image']
                listing.set_sort('size')
                pump()
                for i, row in enumerate(listing.items):
                    role = expected[row.name]
                    assert color(listing, i) == (FILE_COLORS[role] if role else listing.theme_config['text'])
                # A chmod-only refresh must recolor an unselected row without
                # requiring a hover or changing the row's visible text.
                stable_index = next(i for i, row in enumerate(listing.items) if row.name == 'image.png')
                stable_row = listing.items[stable_index]
                listing._display_cell_value(stable_row, 'permissions')
                stable_cache = stable_row._detail_text
                stable_texts = dict(listing._row_for_index(stable_index)['texts'])
                listing.select_indices([stable_index])
                sources = [replace(row, mode=0o100755) if row.name == 'plain.inp' else replace(row)
                           for row in sources]
                panel.refresh_directory(folder, sources)
                pump()
                index = next(i for i, row in enumerate(listing.items) if row.name == 'plain.inp')
                assert color(listing, index) == FILE_COLORS['executable']
                stable_index = next(i for i, row in enumerate(listing.items) if row.name == 'image.png')
                assert listing.items[stable_index] is stable_row
                assert stable_row._detail_text is stable_cache
                assert dict(listing._row_for_index(stable_index)['texts']) == stable_texts
                assert listing.get_selected() == [stable_row]
                assert stable_row.data['source'] is next(row for row in sources if row.name == 'image.png')
            dialog = SettingsDialog(view)
            dialog._ensure_page('general', defer_io=False)
            dialog.show()
            pump(20)
            assert dialog.control_value(dialog.file_colors)
            print('PASS: real Local/Server file colors, metadata refresh cache/native IDs/selection retention, toggling, sorting and Settings')
        finally:
            if dialog is not None:
                dialog.destroy()
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
