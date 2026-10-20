"""Restore every editable Settings page and persist only after Save."""
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

if sys.platform != 'win32':
    raise unittest.SkipTest('requires Windows Dear PyGui')
try:
    from WinUx.ui.components.explorer_list_view import dpg
except (ImportError, OSError) as exc:
    raise unittest.SkipTest('native Dear PyGui unavailable') from exc

from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.preferences.general import GeneralPreferences
from WinUx.preferences.inp import INPPreferences
from WinUx.preferences.performance import PerformancePreferences
from WinUx.preferences.abaqus_versions import AbaqusVersionPreferences
from WinUx.preferences.update import UpdatePreferences


class SettingsResetTests(unittest.TestCase):
    def test_all_page_defaults_are_restored_and_saved(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'APPDATA': root, 'LOCALAPPDATA': root}):
            GeneralPreferences().save(auto_login=True, show_hidden_files=True)
            INPPreferences().save({'formula': INPPreferences.FORMULA_ADAPTIVE,
                                  'dof_per_core': 10000, 'minimum_cores': 16,
                                  'maximum_cores': 256, 'core_step': 8})
            PerformancePreferences().save({key: value * 2 for key, value in PerformancePreferences.DEFAULTS.items()})
            AbaqusVersionPreferences().save(['custom_abaqus', 'abaqus'], 'custom_abaqus')
            UpdatePreferences().save(provider='folder', github_repository='example/custom',
                                     channel='beta', legacy_source=r'X:\Custom')
            saved_event = Mock()
            dpg.create_context()
            try:
                form = SettingsDialog(SimpleNamespace(after=lambda *args: None), on_settings_saved=saved_event)
                form._reset_settings_defaults()
                self.assertFalse(dpg.get_value(form.auto_login))
                self.assertFalse(dpg.get_value(form.show_hidden_files))
                self.assertEqual(form._current_inp_values(), INPPreferences.DEFAULTS)
                self.assertEqual(form._versions, list(AbaqusVersionPreferences.DEFAULT_COMMANDS))
                self.assertEqual(dpg.get_value(form.default_command), AbaqusVersionPreferences.DEFAULT_COMMAND)
                self.assertEqual(dpg.get_value(form.github_repository), UpdatePreferences.defaults()['github_repository'])
                self.assertEqual(dpg.get_value(form.legacy_update_source), '')
                self.assertFalse(form._control_wrappers[form.install_update_button].isEnabled())
                # Reset changes the form first. Cancel can still discard it.
                self.assertTrue(GeneralPreferences().load_show_hidden_files())
                self.assertEqual(INPPreferences().load()['formula'], INPPreferences.FORMULA_ADAPTIVE)
                self.assertEqual(UpdatePreferences().load()['channel'], 'beta')
                saved_event.assert_not_called()

                form._save()
                self.assertFalse(GeneralPreferences().load_auto_login())
                self.assertFalse(GeneralPreferences().load_show_hidden_files())
                self.assertEqual(INPPreferences().load(), INPPreferences.DEFAULTS)
                performance = PerformancePreferences().load()
                for key, value in PerformancePreferences.DEFAULTS.items():
                    self.assertAlmostEqual(performance[key], value, places=6)
                self.assertEqual(AbaqusVersionPreferences().load_settings(), {
                    'versions': list(AbaqusVersionPreferences.DEFAULT_COMMANDS),
                    'default_command': AbaqusVersionPreferences.DEFAULT_COMMAND})
                self.assertEqual(UpdatePreferences().load(), UpdatePreferences.defaults())
                saved_event.assert_called_once_with({'auto_login': False, 'show_hidden_files': False})
            finally:
                dpg.destroy_context()
