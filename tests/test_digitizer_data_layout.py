"""Command rows must not consume the panel height above the data grid."""
import sys
import unittest


@unittest.skipUnless(sys.platform == "win32", "Requires the native Win32 renderer")
class DigitizerDataLayoutTests(unittest.TestCase):
    def test_data_rows_visible_and_automatic_page_has_no_spurious_scroll(self):
        from tools.check_digitizer_data_layout import main
        main()


if __name__ == "__main__":
    unittest.main()
