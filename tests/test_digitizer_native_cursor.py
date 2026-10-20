import sys
import unittest


@unittest.skipUnless(sys.platform == "win32", "Requires the native Win32 renderer")
class NativeDigitizerCursorTests(unittest.TestCase):
    def test_native_cursor_modes_and_overlay(self):
        from tools.check_digitizer_cursor import main
        main()


if __name__ == "__main__":
    unittest.main()
