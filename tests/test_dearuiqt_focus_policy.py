from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.core.object import Qt
from DearUIQt.widgets.widget import QWidget
from DearUIQt.widgets.buttons import ImGuiLabel
from DearUIQt.dialogs import qt_dialog as qt_dialog_module
from DearUIQt.dialogs.qt_dialog import QtDialog


class Backend:
    def __init__(self):
        self.next_tag = 100
        self.alive = set()

    def add_text(self, value, **_options):
        self.next_tag += 1
        self.alive.add(self.next_tag)
        return self.next_tag

    def does_item_exist(self, tag):
        return tag in self.alive or isinstance(tag, int)

    def configure_item(self, *_args, **_kwargs):
        return None

    def delete_item(self, tag):
        self.alive.discard(tag)

    def get_item_configuration(self, _tag):
        return {'enabled': True, 'show': True}


class FocusPolicyTests(unittest.TestCase):
    def test_focus_policy_values_match_qt_bit_contract(self):
        self.assertEqual(Qt.NoFocus, 0)
        self.assertTrue(Qt.StrongFocus & Qt.TabFocus)
        self.assertTrue(Qt.StrongFocus & Qt.ClickFocus)
        self.assertTrue(Qt.WheelFocus & Qt.StrongFocus)

    def test_widget_focus_policy_round_trip(self):
        backend = Backend()
        widget = QWidget(1, backend=backend)
        self.assertEqual(widget.focusPolicy(), Qt.StrongFocus)
        widget.setFocusPolicy(Qt.ClickFocus)
        self.assertFalse(widget.acceptsTabFocus())
        self.assertTrue(widget.acceptsClickFocus())
        with self.assertRaises(ValueError):
            widget.setFocusPolicy(0x4000)
        widget.delete()

    def test_label_defaults_to_no_focus(self):
        backend = Backend()
        label = ImGuiLabel('Status', backend=backend)
        self.assertEqual(label.focusPolicy(), Qt.NoFocus)
        self.assertFalse(label.acceptsTabFocus())
        label.delete()

    def test_focus_proxy_resolves_and_rejects_cycles(self):
        backend = Backend()
        first = QWidget(1, backend=backend)
        second = QWidget(2, backend=backend)
        third = QWidget(3, backend=backend)
        first.setFocusProxy(second)
        second.setFocusProxy(third)
        self.assertIs(first.focusProxy(), second)
        self.assertIs(first._effective_focus_widget(), third)
        with self.assertRaises(ValueError):
            third.setFocusProxy(first)
        third.delete()
        self.assertIsNone(second.focusProxy())
        first.delete()
        second.delete()

    def test_dialog_tab_focus_honors_policy_and_proxy(self):
        backend = Backend()
        first = QWidget(1, backend=backend)
        ignored = QWidget(2, backend=backend)
        proxy_owner = QWidget(3, backend=backend)
        proxy = QWidget(4, backend=backend)
        ignored.setFocusPolicy(Qt.ClickFocus)
        proxy_owner.setFocusProxy(proxy)

        dialog = object.__new__(QtDialog)
        dialog._control_wrappers = {1: first, 2: ignored, 3: proxy_owner, 4: proxy}
        dialog._focus_order = [1, 2, 3]
        dialog._default_button = None
        focused = []
        dialog.focus_control = lambda tag: focused.append(tag) or True
        dialog._activation_owned = False

        fake_dpg = SimpleNamespace(
            does_item_exist=lambda _tag: True,
            is_item_shown=lambda _tag: True,
            get_item_configuration=lambda _tag: {'enabled': True},
            get_focused_item=lambda: 1,
        )
        with patch.object(qt_dialog_module, 'dpg', fake_dpg):
            self.assertTrue(dialog.focusNextPrevChild(next=True))
            # ClickFocus-only widget 2 is skipped; wrapper 3 resolves to proxy 4.
            self.assertEqual(focused[-1], 4)

        for widget in (first, ignored, proxy_owner, proxy):
            if not widget._deleted:
                widget.delete()


if __name__ == '__main__':
    unittest.main()
