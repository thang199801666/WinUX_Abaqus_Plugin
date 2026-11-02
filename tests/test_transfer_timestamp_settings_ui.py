"""Real Settings Save/Cancel/defaults for source-file modification times."""
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
from WinUx.dialogs.settings_form import SettingsDialog
from WinUx.preferences.general import GeneralPreferences
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(dir=root) as profile, patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        dialogs = []
        def pump(count=10):
            for _ in range(count):
                view.update()
                time.sleep(.005)
        def open_settings():
            dialog = SettingsDialog(view)
            dialogs.append(dialog)
            dialog._ensure_page('general', defer_io=False)
            dialog.show()
            pump(15)
            return dialog
        try:
            view._gui_runtime.show()
            self_prefs = GeneralPreferences()
            dialog = open_settings()
            assert view._preserve_file_timestamps and dialog.control_value(dialog.preserve_file_timestamps)
            dialog.set_control_value(dialog.preserve_file_timestamps, False)
            dialog._save()
            pump()
            assert not self_prefs.load()['preserve_file_timestamps']
            assert not view._preserve_file_timestamps
            dialog = open_settings()
            assert not dialog.control_value(dialog.preserve_file_timestamps)
            dialog.set_control_value(dialog.preserve_file_timestamps, True)
            dialog.destroy()
            pump()
            assert not self_prefs.load()['preserve_file_timestamps'] and not view._preserve_file_timestamps
            dialog = open_settings()
            dialog._reset_settings_defaults()
            assert dialog.control_value(dialog.preserve_file_timestamps)
            dialog._save()
            pump()
            assert self_prefs.load()['preserve_file_timestamps'] and view._preserve_file_timestamps
            print('PASS: timestamp checkbox default, Save applies to new tasks, Cancel discards edits, reopening and Restore Defaults')
        finally:
            for dialog in dialogs:
                dialog.destroy()
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
