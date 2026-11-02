"""Real Local/Server Odb Tools submenu construction and keyboard opening."""
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
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.ui.components.explorer_list_view import ListViewItem
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-odb-tools-menu-', dir=root) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        callbacks = {key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS}
        callbacks['server_connected'] = lambda: True
        view = WinUXView(callbacks)
        def pump(count=8):
            for _ in range(count):
                view.update()
                time.sleep(.01)
        try:
            view._gui_runtime.show()
            pump()
            for panel in view.panels:
                item = ListViewItem(name='sample.odb', path='C:/test/sample.odb',
                                    is_dir=False, item_type='ODB file')
                panel.listview.set_items([item])
                panel.listview.select_indices([0])
                panel._context_menu_open([item])
                panel.listview._context_item_index = 0
                panel.listview._show_item_context_menu((250, 200))
                pump()
                menu = panel.listview._item_context_menu
                menu._set_active_action('odb_tools_group')
                assert menu.navigate('right'), 'Odb Tools submenu did not open'
                pump()
                submenu = menu._submenus['odb_tools_group']
                expected = (['Quick Check', 'Extract Data', 'Upgrade ODB']
                            if panel.panel_id == 'server' else ['Quick Check', 'Upgrade ODB'])
                assert [entry['label'] for entry in submenu._actions] == expected
                assert all(entry.get('enabled', True) for entry in submenu._actions)
                assert submenu.isVisible()
                menu.hide()
                pump(3)
            print('PASS: real Local/Server Odb Tools menus, submenu opening and ODB action states', flush=True)
        finally:
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
