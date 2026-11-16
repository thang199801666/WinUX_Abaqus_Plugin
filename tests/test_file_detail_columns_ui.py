"""Real Local/Server column chooser, rendering and selection preservation."""
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.models.items import FileItem
from WinUx.ui.components.explorer_list_model import EXTRA_FILE_COLUMNS
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        def pump():
            for _ in range(8):
                view.update()
                time.sleep(.01)
        try:
            view._gui_runtime.show()
            pump()
            for panel in view.panels:
                folder = PurePosixPath('/test') if panel.panel_id == 'server' else Path(profile)
                source = FileItem('example.inp', folder / 'example.inp', False, 42, 100,
                                  mode=0o100640, uid=1000, gid=100, accessed=200,
                                  created=100, attributes=3,
                                  owner_name='engineer', group_name='analysis')
                panel.display(folder, [source])
                listing = panel.listview
                listing.select_indices([0])
                pump()
                assert len(listing._visible_columns()) == 4
                assert listing._display_cell_value(listing.items[0], 'owner') == 'engineer'
                assert listing._display_cell_value(listing.items[0], 'group') == 'analysis'
                specs = {entry['id']: entry for entry in listing._header_menu_specs()}
                for key, _, _ in EXTRA_FILE_COLUMNS:
                    assert not specs['column:' + key]['checked']
                    listing._on_header_menu_triggered('column:' + key)
                    pump()
                    assert listing.get_column(key)['visible']
                    assert listing._display_cell_value(listing.items[0], key)
                    listing.set_sort(key)
                    pump()
                    assert listing.get_selected()[0].name == 'example.inp'
                    listing._on_header_menu_triggered('column:' + key)
                    pump()
                changed = FileItem('example.inp', folder / 'example.inp', False, 42, 100,
                                   mode=0o100600, uid=1000, gid=100, accessed=200,
                                   created=100, attributes=3,
                                   owner_name='engineer', group_name='analysis')
                panel.refresh_directory(folder, [changed])
                pump()
                assert listing._display_cell_value(listing.items[0], 'permissions') == '-rw------- (0600)'
                assert listing.get_selected()[0].name == 'example.inp'
                assert len(listing._visible_columns()) == 4
            for panel in view.panels:
                panel.listview.set_auto_width(True)
            for width in (900, 1100, 760):
                view._gui_runtime.configureViewport(width=width, height=650)
                pump()
                for panel in view.panels:
                    listing = panel.listview
                    columns_width = sum(listing._column_widths[c['key']]
                                        for c in listing._visible_columns())
                    assert abs(columns_width - listing._available_width()) <= 1
                    assert not getattr(listing, '_auto_width_resize_sync_pending', False)
                    assert listing.get_selected()[0].name == 'example.inp'
            print('PASS: Local/Server hidden detail columns, chooser, values, sorting and permission-only refresh')
        finally:
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
