import unittest

from DearUIQt.gui.action import QAction
from DearUIQt.ribbon import RibbonBar


class _Context:
    def __init__(self, tag): self.tag = tag
    def __enter__(self): return self.tag
    def __exit__(self, *_args): return False


class _Backend:
    def __init__(self):
        self._next = 10
        self.config = {}
        self.callbacks = {}
    def _id(self):
        self._next += 1
        return self._next
    def __getattr__(self, name):
        if name.startswith("mv"): return name
        raise AttributeError(name)
    def theme(self): return _Context(self._id())
    def theme_component(self, *_args, **_kwargs): return _Context(self._id())
    def add_theme_color(self, *_args, **_kwargs): return self._id()
    def add_theme_style(self, *_args, **_kwargs): return self._id()
    def add_child_window(self, **_kwargs): return self._id()
    def add_group(self, **_kwargs): return self._id()
    def add_button(self, **kwargs):
        tag = self._id()
        if kwargs.get("callback") is not None:
            self.callbacks[tag] = kwargs["callback"]
        self.config[tag] = dict(kwargs)
        return tag
    def add_text(self, *_args, **_kwargs): return self._id()
    def add_spacer(self, **_kwargs): return self._id()
    def add_drawlist(self, **_kwargs): return self._id()
    def draw_line(self, *_args, **_kwargs): return self._id()
    def bind_item_theme(self, *_args, **_kwargs): return None
    def configure_item(self, tag, **kwargs): self.config.setdefault(tag, {}).update(kwargs)
    def does_item_exist(self, _tag): return True
    def delete_item(self, _tag): return None


class RibbonQActionTests(unittest.TestCase):
    def _build(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend)
        tab = ribbon.create_tab("home", "Home")
        group = tab.add_group("edit", "Edit", layout="small")
        return backend, ribbon, group

    def test_action_is_single_source_of_truth(self):
        backend, ribbon, group = self._build()
        action = QAction("Run", ribbon, checkable=True, checked=False)
        action.setToolTip("Execute")
        button = group.add_action(action, key="run", size="small")
        self.assertIs(ribbon.action_for_button("run"), action)
        self.assertFalse(button.is_checked())

        action.setText("Run now")
        action.setEnabled(False)
        action.setVisible(False)
        action.setChecked(True)
        record = ribbon._buttons["run"]
        self.assertEqual(record["label"], "Run now")
        self.assertFalse(record["enabled"])
        self.assertFalse(record["visible"])
        self.assertTrue(record["checked"])

    def test_ribbon_click_triggers_qaction_and_qaction_owns_toggle(self):
        _backend, ribbon, group = self._build()
        action = QAction("Toggle", ribbon, checkable=True)
        seen = []
        action.triggered.connect(lambda checked: seen.append(bool(checked)))
        group.add_action(action, key="toggle")
        ribbon._button_clicked("toggle")
        self.assertTrue(action.isChecked())
        self.assertTrue(ribbon.is_button_checked("toggle"))
        self.assertEqual(seen, [True])

    def test_destroyed_action_disables_bound_button(self):
        _backend, ribbon, group = self._build()
        action = QAction("Delete me", ribbon)
        group.add_action(action, key="delete")
        action.delete()
        self.assertIsNone(ribbon.action_for_button("delete"))
        self.assertFalse(ribbon._buttons["delete"]["enabled"])


if __name__ == "__main__":
    unittest.main()
