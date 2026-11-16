"""Retained RibbonBar adaptive layout tests using a minimal headless backend."""
import unittest

from DearUIQt.ribbon import RibbonBar


class _Context:
    def __init__(self, tag):
        self.tag = tag

    def __enter__(self):
        return self.tag

    def __exit__(self, *_args):
        return False


class _Backend:
    def __init__(self):
        self._next = 10
        self.config = {}

    def _id(self):
        self._next += 1
        return self._next

    def __getattr__(self, name):
        if name.startswith("mv"):
            return name
        raise AttributeError(name)

    def theme(self):
        return _Context(self._id())

    def theme_component(self, *_args, **_kwargs):
        return _Context(self._id())

    def add_theme_color(self, *_args, **_kwargs):
        return self._id()

    def add_theme_style(self, *_args, **_kwargs):
        return self._id()

    def add_child_window(self, **_kwargs):
        return self._id()

    def add_group(self, **_kwargs):
        return self._id()

    def add_button(self, **_kwargs):
        return self._id()

    def add_text(self, *_args, **_kwargs):
        return self._id()

    def add_spacer(self, **_kwargs):
        return self._id()

    def add_drawlist(self, **_kwargs):
        return self._id()

    def draw_line(self, *_args, **_kwargs):
        return self._id()

    def bind_item_theme(self, *_args, **_kwargs):
        return None

    def configure_item(self, tag, **kwargs):
        self.config.setdefault(tag, {}).update(kwargs)

    def does_item_exist(self, _tag):
        return True

    def delete_item(self, _tag):
        return None


class RibbonAdaptiveRuntimeTests(unittest.TestCase):
    def _build(self, template="classic"):
        ribbon = RibbonBar(1, backend=_Backend(), display_template=template)
        tab = ribbon.create_tab("home", "Home")
        first = tab.add_group("first", "First", width=220, layout="large")
        first.add_button("a", "Alpha", size="large")
        second = tab.add_group("second", "Second", width=180, layout="small")
        second.add_button("b", "Beta", size="small")
        second.add_button("c", "Gamma", size="small")
        third = tab.add_group("third", "Third", width=160, layout="small")
        third.add_button("d", "Delta", size="small")
        return ribbon, first, second, third

    def test_runtime_reduces_before_collapsing(self):
        ribbon, first, second, third = self._build()
        wide = ribbon.set_responsive(True, width=800)["home"]
        medium = ribbon.handle_resize(460)["home"]
        self.assertFalse(wide.overflow)
        self.assertTrue(all(group.state == "large" for group in wide.groups))
        self.assertFalse(medium.overflow)
        self.assertIn(first.display_state, ("large", "medium", "small"))
        self.assertIn(second.display_state, ("medium", "small"))
        self.assertIn(third.display_state, ("medium", "small"))

    def test_runtime_collapses_and_restores_natural_state(self):
        ribbon, first, second, third = self._build("large-icons")
        narrow = ribbon.set_responsive(True, width=210)["home"]
        self.assertTrue(narrow.overflow)
        self.assertEqual(third.display_state, "collapsed")
        ribbon.set_responsive(False)
        self.assertEqual(first.display_state, "large")
        self.assertEqual(second.display_state, "large")
        self.assertEqual(third.display_state, "large")


if __name__ == "__main__":
    unittest.main()
