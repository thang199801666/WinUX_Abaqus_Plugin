"""Real Settings rule editing and saved Local/Server recoloring (no SSH)."""
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
from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.models.items import FileItem
from WinUx.preferences.general import GeneralPreferences
from WinUx.services.file_color_rules import default_color_rules
from WinUx.view import WinUXView


def main():
    temporary_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=temporary_root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialogs = []
        def pump(count=8):
            for _ in range(count):
                view.update()
                time.sleep(.005)
        def open_colors():
            dialog = SettingsDialog(view)
            dialogs.append(dialog)
            dialog._ensure_page('general', defer_io=False)
            dialog._ensure_page('colors', defer_io=False)
            dialog._show_page('colors')
            dialog.show()
            pump(15)
            return dialog
        def text_color(listing, name):
            index = next(i for i, item in enumerate(listing.items) if item.name == name)
            row = listing._row_for_index(index)
            return tuple(round(v * 255) for v in dpg.get_item_configuration(row['texts']['name'])['color'])
        try:
            view._gui_runtime.show()
            for panel in view.panels:
                folder = PurePosixPath('/colors') if panel.panel_id == 'server' else Path(profile)
                panel.display(folder, [FileItem(name, folder / name, False, 42, time.time())
                                       for name in ('model.inp', 'result.odb', 'skip.bak')])
                panel.listview.select_indices([])
                panel.apply_filter('*.*')
                assert len(panel.listview.items) == 3
                panel.apply_filter('*.inp,*.odb>=1|skip*')
                assert {item.name for item in panel.listview.items} == {'model.inp', 'result.odb'}
                panel.listview.select_indices([0])
                before_items = list(panel.listview.items)
                before_selection = set(panel.listview.selected)
                assert panel.apply_filter('*.inp>') is False
                assert panel.listview.items == before_items
                assert panel.listview.selected == before_selection
                panel.apply_filter('*/model.inp>=1')
                assert [item.name for item in panel.listview.items] == ['model.inp']
                panel.apply_filter('*.odb>=2020-01-01')
                assert [item.name for item in panel.listview.items] == ['result.odb']
                panel.apply_filter('')
                panel.listview.select_indices([])
            dialog = open_colors()
            assert len(dialog._color_rules_draft) == 6
            # Exercise the native picker's callback contract, not only the hex editor.
            dialog.color_rule_color._picked(None, (20, 80, 140, 255))
            assert dialog.color_rule_color.editor.text() == '#14508C'
            dialog._restore_color_defaults()
            dialog._edit_color_rule('add')
            assert dialog._color_rule_index == 0, 'Add must insert before the selected rule'
            dialog.set_control_value(dialog.color_rule_name, 'Abaqus models')
            dialog.set_control_value(dialog.color_rule_mask, '*/model.inp>=1,*.odb>=2020-01-01|*.bak')
            dialog.color_rule_color.editor.setText('#C02080')
            dialog._edit_color_rule('update')
            assert dialog._color_rules_draft[0]['color'] == '#C02080'
            dialog.set_control_value(dialog._color_rule_enabled.tag, False)
            dialog._edit_color_rule('update')
            assert not dialog._color_rules_draft[0]['enabled']
            dialog.set_control_value(dialog._color_rule_enabled.tag, True)
            dialog._edit_color_rule('update')
            dialog._edit_color_rule('down')
            assert dialog._color_rule_index == 1
            dialog._edit_color_rule('up')
            assert dialog._color_rule_index == 0
            # Switching rows auto-commits pending edits; bad values keep focus
            # on the old rule and cannot persist partial settings.
            valid_mask = dialog.control_value(dialog.color_rule_mask)
            dialog.set_control_value(dialog.color_rule_mask, '*.inp>')
            dialog._save()
            assert dialog.isVisible()
            assert GeneralPreferences().load()['file_color_rules'] == default_color_rules()
            dialog.set_control_value(dialog.color_rule_mask, valid_mask)
            dialog.color_rule_color.editor.setText('invalid')
            dialog.color_rule_list.setCurrentRow(2)
            assert dialog._color_rule_index == 0
            assert dialog.color_rule_list.currentRow() == 0
            dialog._save()
            assert dialog.isVisible()
            assert GeneralPreferences().load()['file_color_rules'] == default_color_rules()
            dialog.color_rule_color.editor.setText('#C02080')
            dialog.set_control_value(dialog.color_rule_name, 'Abaqus files')
            dialog.color_rule_list.setCurrentRow(1)
            assert dialog._color_rules_draft[0]['name'] == 'Abaqus files'
            pump(3)
            dialog._save()
            pump(5)
            rules = GeneralPreferences().load()['file_color_rules']
            assert rules[0]['name'] == 'Abaqus files' and rules[0]['color'] == '#C02080'
            for panel in view.panels:
                listing = panel.listview
                assert text_color(listing, 'model.inp') == (192, 32, 128, 255)
                assert text_color(listing, 'result.odb') == (192, 32, 128, 255)
                assert text_color(listing, 'skip.bak') == listing.theme_config['text']
                index = next(i for i, item in enumerate(listing.items) if item.name == 'model.inp')
                listing.select_indices([index])
                selected = set(listing.selected)
                panel.set_file_colors(False)
                assert listing.selected == selected
                panel.set_file_colors(True)
                assert listing.selected == selected
                listing.refresh_row_visuals()
                pump(2)
                expected = listing.theme_config['selected_text' if listing._has_focus else 'inactive_selected_text']
                assert text_color(listing, 'model.inp') == expected
            dialog = open_colors()
            assert dialog._color_rules_draft == rules
            dialog._restore_color_defaults()
            assert dialog._color_rules_draft == default_color_rules()
            dialog.destroy()
            assert GeneralPreferences().load()['file_color_rules'] == rules, 'Cancel persisted draft defaults'
            dialog = open_colors()
            while dialog._color_rules_draft:
                dialog._edit_color_rule('remove')
            assert dialog._collect_color_rules() == []
            dialog._edit_color_rule('add')
            assert len(dialog._color_rules_draft) == 1
            dialog._restore_color_defaults()
            dialog._save()
            assert GeneralPreferences().load()['file_color_rules'] == default_color_rules()
            print('PASS: real File Colors page, picker/hex editor, Add/Update/Remove, priority, validation, Save/Cancel, persistence, defaults, both panels and selection protection')
        finally:
            for dialog in dialogs:
                dialog.destroy()
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
