"""Unused tool trees stay unallocated; tools still open and reuse on demand."""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.view import WinUXView


def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-lazy-tools-', dir=root) as profile, \
            patch.dict(os.environ, {'APPDATA': profile}):
        view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
        def pump(count=12):
            for _ in range(count):
                view.update()
                time.sleep(.01)
        try:
            view._gui_runtime.show()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                pump(1)
            for name in ('settings_dialog', 'diagnostics_dialog', 'transfer_center_dialog'):
                assert getattr(view, name, None) is None, 'Unused tool allocated: ' + name
            for show in (view.show_settings, view.show_diagnostics, view.show_transfer_center):
                dialog = show()
                pump()
                assert dialog.winfo_exists()
                dialog.hide()
                pump(3)
                assert show() is dialog, 'Opening a tool twice duplicated its widget tree'
                pump(3)
                dialog.hide()
                pump(3)
            # Expiry affects only acknowledged blank hosts, never leases/tool data.
            pool = getattr(view, '_dialog_host_pool', None)
            if pool is not None:
                pool.trim_idle(0)
                for dialog in (view.settings_dialog, view.diagnostics_dialog,
                               view.transfer_center_dialog):
                    assert dialog.winfo_exists()
            print('PASS: lazy Settings/Diagnostics/Transfer Center, reuse and safe idle-host trim', flush=True)
        finally:
            view.request_shutdown()
            view._destroy_components()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
