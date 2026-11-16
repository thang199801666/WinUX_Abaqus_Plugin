import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UndockedConsoleContextRouteSourceTests(unittest.TestCase):
    def test_floating_viewport_bridges_context_messages(self):
        source = (ROOT / "WinUx/ui/native/floating_viewport.py").read_text(encoding="utf-8")
        self.assertIn('message in (0x0205, 0x007B)', source)
        self.assertIn('context_callback', source)
        self.assertIn('view.after(delay, context_callback, position)', source)

    def test_runtime_passes_exact_floating_hwnd_to_console(self):
        source = (ROOT / "WinUx/ui/hosting/floating_runtime.py").read_text(encoding="utf-8")
        self.assertIn('native_client=True, native_hwnd=self.native.hwnd', source)
        self.assertIn('initial.get("kind") in ("console", "console_dock")', source)

    def test_detached_console_renders_menu_inside_primary_host(self):
        source = (ROOT / "WinUx/dialogs/console/console_form.py").read_text(encoding="utf-8")
        self.assertIn('def _native_floating_context_menu(self, position, hwnd):', source)
        self.assertIn('is_standalone_ui_host', source)
        self.assertIn('parent_window=parent_window', source)
        self.assertIn('def _popup_context_menu(self, position=None, *, native_hwnd=0):', source)
        self.assertIn('ScreenToClient', source)
        self.assertIn('menu.popup((x, y), context=self)', source)
        self.assertNotIn('TrackPopupMenuEx', source)
        self.assertIn('if native_client and native_hwnd:', source)
        self.assertIn('self._native_floating_context_menu(position, native_hwnd)', source)


if __name__ == "__main__":
    unittest.main()
