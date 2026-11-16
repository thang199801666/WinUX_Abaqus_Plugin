import unittest

from WinUx.server_model import SSHServerModel


class ShellAltScreenFilterTests(unittest.TestCase):
    def test_alternate_screen_does_not_pollute_visible_transcript(self):
        model = SSHServerModel()
        first = model._filter_alt_screen_transcript_locked(
            "prompt$ nano file.txt\r\n\x1b[?1049hSCREEN")
        self.assertIn("prompt$ nano file.txt", first)
        self.assertNotIn("SCREEN", first)
        self.assertTrue(model._shell_alt_screen_active)
        middle = model._filter_alt_screen_transcript_locked("MORE SCREEN\x1b[2J")
        self.assertEqual(middle, "")
        last = model._filter_alt_screen_transcript_locked(
            "\x1b[?1049l\r\nprompt$ ")
        self.assertIn("prompt$ ", last)
        self.assertFalse(model._shell_alt_screen_active)

    def test_split_enter_and_exit_sequences(self):
        model = SSHServerModel()
        self.assertEqual(model._filter_alt_screen_transcript_locked("abc\x1b[?104"), "abc")
        self.assertEqual(model._filter_alt_screen_transcript_locked("9hhidden"), "")
        self.assertTrue(model._shell_alt_screen_active)
        self.assertEqual(model._filter_alt_screen_transcript_locked("\x1b[?1049"), "")
        self.assertEqual(model._filter_alt_screen_transcript_locked("lxyz"), "xyz")
        self.assertFalse(model._shell_alt_screen_active)


if __name__ == "__main__":
    unittest.main()
