import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from WinUx.components.explorer_themes import ListViewTheme, ListViewThemeManager
from WinUx.platform.windows_cursors import WindowsCursorFile


class ThemeTests(unittest.TestCase):
    def test_theme_aliases_and_case_insensitive_names(self):
        for alias, name in (("vscode", "VS Code"), (" DARKBLUE ", "Dark Blue"), ("winscp", "WinSCP")):
            self.assertEqual(ListViewThemeManager.resolve(alias)[0], name)
        self.assertEqual(ListViewThemeManager.resolve(None)[0], ListViewTheme.EXPLORER)

    def test_resolved_configuration_is_detached_from_registry(self):
        name, config = ListViewThemeManager.resolve("Explorer")
        original = config["background"]
        config["background"] = (0, 0, 0, 0)
        self.assertEqual(ListViewThemeManager.resolve(name)[1]["background"], original)

    def test_custom_theme_inherits_and_can_be_removed(self):
        name = "test_resource_theme"
        config = {"text": (1, 2, 3, 255)}
        try:
            ListViewThemeManager.register(name, config, base="WinSCP")
            config["text"] = None
            resolved = ListViewThemeManager.resolve(name)[1]
            self.assertEqual(resolved["text"], (1, 2, 3, 255))
            self.assertEqual(resolved["selected_text"], (255, 255, 255, 255))
            with self.assertRaises(KeyError):
                ListViewThemeManager.register(name, {})
        finally:
            ListViewThemeManager.unregister(name)
        self.assertNotIn(name, ListViewThemeManager.available())

    def test_core_theme_cannot_be_removed_and_bad_names_rejected(self):
        with self.assertRaises(ValueError):
            ListViewThemeManager.unregister("Explorer")
        with self.assertRaises(KeyError):
            ListViewThemeManager.resolve("missing_theme")
        with self.assertRaises(TypeError):
            ListViewThemeManager.resolve({})


class CursorTests(unittest.TestCase):
    def test_cursor_loader_caches_by_path_and_size(self):
        import WinUx.platform.windows_cursors as module
        user32 = SimpleNamespace(GetSystemMetrics=Mock(side_effect=lambda key: {13: 32, 14: 48}[key]),
                                 LoadImageW=Mock(return_value=123))
        native = SimpleNamespace(windll=SimpleNamespace(user32=user32), c_int=ctypes.c_int,
                                 c_void_p=ctypes.c_void_p)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.cur"
            path.write_bytes(b"test-only mock cursor")
            with patch.object(module, "os", SimpleNamespace(name="nt", path=os.path)), \
                 patch.object(module, "ctypes", native), patch.object(WindowsCursorFile, "_cache", {}):
                self.assertEqual(WindowsCursorFile.load(str(path)), 123)
                self.assertEqual(WindowsCursorFile.load(str(path)), 123)
                user32.LoadImageW.assert_called_once()
                args = user32.LoadImageW.call_args.args
                self.assertEqual(args[3:5], (32, 48))
                WindowsCursorFile.load(str(path), width=16, height=16)
                self.assertEqual(user32.LoadImageW.call_count, 2)

    def test_cursor_functions_are_safe_without_windows(self):
        import WinUx.platform.windows_cursors as module
        with patch.object(module, "os", SimpleNamespace(name="posix")):
            self.assertEqual(WindowsCursorFile.system_size(), (0, 0))
            self.assertIsNone(WindowsCursorFile.load("missing"))
            self.assertIsNone(WindowsCursorFile.create_copy_cursor())
