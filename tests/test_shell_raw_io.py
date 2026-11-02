import unittest

from WinUx.server_model import SSHServerModel


class _FakeShell:
    def __init__(self):
        self.closed = False
        self.sent = []
        self.resizes = []

    def send(self, data):
        self.sent.append(data)
        return len(data)

    def resize_pty(self, width, height):
        self.resizes.append((width, height))


class ShellRawIOTests(unittest.TestCase):
    def test_raw_input_is_not_line_buffered(self):
        model = SSHServerModel()
        shell = _FakeShell()
        model.shell = shell
        self.assertTrue(model.send_shell_input("\x18"))
        self.assertEqual(shell.sent, ["\x18"])

    def test_resize_matches_terminal_grid(self):
        model = SSHServerModel()
        shell = _FakeShell()
        model.shell = shell
        self.assertTrue(model.resize_shell_pty(91, 27))
        self.assertEqual(shell.resizes, [(91, 27)])


if __name__ == "__main__":
    unittest.main()
