from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QWindowHostFloatingRuntimeIntegrationTests(unittest.TestCase):
    def test_floating_runtime_publishes_native_hwnd_to_gui_runtime(self):
        text = (ROOT / 'WinUx/ui/hosting/floating_runtime.py').read_text(encoding='utf-8')
        self.assertIn('self.gui.setNativeHandle(self.native.hwnd)', text)

    def test_plotdigitizer_standalone_publishes_native_hwnd(self):
        text = (ROOT / 'WinUx/plotdigitizer/standalone.py').read_text(encoding='utf-8')
        self.assertIn('runtime.setNativeHandle(native.hwnd)', text)


if __name__ == '__main__':
    unittest.main()
