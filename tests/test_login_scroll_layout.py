"""Render the login with the main application's font, not the smaller host font."""
import sys
import unittest


@unittest.skipUnless(sys.platform == "win32", "Requires the native Win32 renderer")
class LoginScrollLayoutTests(unittest.TestCase):
    def test_application_font_fits_without_body_scrollbar(self):
        from tools.check_login_scroll import main
        main()


if __name__ == "__main__":
    unittest.main()
