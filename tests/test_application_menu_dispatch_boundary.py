import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WinUx.ui.behaviors.window.application_menu import ApplicationMenuMixin


class _Host(ApplicationMenuMixin):
    def __init__(self):
        self.queued = []
    def after_render(self, callback, *args):
        self.queued.append((callback, args))
        return len(self.queued)


class ApplicationMenuDispatchBoundaryTests(unittest.TestCase):
    def test_command_is_not_run_inline(self):
        host = _Host()
        called = []
        token = host._dispatch_application_menu_callback(
            'Settings...', lambda: called.append('settings'))
        self.assertEqual(token, 1)
        self.assertEqual(called, [])
        callback, args = host.queued.pop(0)
        callback(*args)
        self.assertEqual(called, ['settings'])

    def test_arguments_survive_render_boundary(self):
        host = _Host()
        called = []
        host._dispatch_application_menu_callback(
            'Plots', lambda value: called.append(value), True)
        callback, args = host.queued.pop(0)
        callback(*args)
        self.assertEqual(called, [True])

    def test_missing_handler_fails_at_dispatch_boundary_with_action_name(self):
        host = _Host()
        with self.assertRaisesRegex(TypeError, 'Broken'):
            host._dispatch_application_menu_callback('Broken', None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
