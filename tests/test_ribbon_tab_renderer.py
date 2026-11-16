"""Tests for retained ribbon tab rendering and generic appearance derivation."""
import unittest

from DearUIQt.ribbon import RibbonAppearanceTemplateFactory, RibbonBar


class _Context:
    def __init__(self, tag): self.tag = tag
    def __enter__(self): return self.tag
    def __exit__(self, *_args): return False


class _Backend:
    def __init__(self):
        self._next = 100
        self.config = {}
        self.bindings = []
        self.lines = {}
        self.rects = {}
        self.texts = {}
    def _id(self):
        self._next += 1
        return self._next
    def __getattr__(self, name):
        if name.startswith("mv"):
            return name
        raise AttributeError(name)
    def theme(self): return _Context(self._id())
    def theme_component(self, *_args, **_kwargs): return _Context(self._id())
    def add_theme_color(self, *_args, **_kwargs): return self._id()
    def add_theme_style(self, *_args, **_kwargs): return self._id()
    def add_child_window(self, **_kwargs): return self._id()
    def add_group(self, **_kwargs): return self._id()
    def add_button(self, **_kwargs): return self._id()
    def add_text(self, *_args, **_kwargs): return self._id()
    def add_spacer(self, **_kwargs): return self._id()
    def add_drawlist(self, **_kwargs): return self._id()
    def draw_line(self, p1, p2, **kwargs):
        tag = self._id()
        self.lines[tag] = {"p1": p1, "p2": p2, **kwargs}
        return tag
    def draw_rectangle(self, pmin, pmax, **kwargs):
        tag = self._id()
        self.rects[tag] = {"pmin": pmin, "pmax": pmax, **kwargs}
        return tag
    def draw_text(self, pos, text, **kwargs):
        tag = self._id()
        self.texts[tag] = {"pos": pos, "text": text, **kwargs}
        return tag
    def bind_item_theme(self, tag, theme): self.bindings.append((tag, theme))
    def configure_item(self, tag, **kwargs): self.config.setdefault(tag, {}).update(kwargs)
    def does_item_exist(self, _tag): return True
    def delete_item(self, _tag): return None


class RibbonTabRendererTests(unittest.TestCase):
    def test_underline_uses_real_retained_indicator(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="modern-clean")
        ribbon.create_tab("home", "Home")
        record = ribbon._tabs["home"]
        self.assertNotEqual(record["host"], record["header"])
        self.assertNotEqual(record["indicator"], record["header"])
        self.assertTrue(backend.config[record["indicator"]]["show"])
        self.assertEqual(
            backend.config[record["indicator_line"]]["color"],
            ribbon.visual_style.tab_active_border,
        )

    def test_render_switch_reuses_tab_primitives(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="modern-clean")
        ribbon.create_tab("home", "Home")
        record = ribbon._tabs["home"]
        identity = (record["host"], record["header"], record["indicator"])

        ribbon.set_render_styles(tab_style="pill")
        self.assertFalse(backend.config[record["indicator"]]["show"])
        ribbon.set_render_styles(tab_style="underline")
        self.assertTrue(backend.config[record["indicator"]]["show"])
        self.assertEqual(identity, (record["host"], record["header"], record["indicator"]))

    def test_per_tab_accent_is_content_agnostic_and_runtime_mutable(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="modern-clean")
        tab = ribbon.create_tab("one", "One", accent=(10, 20, 30))
        self.assertEqual(tab.accent, (10, 20, 30, 255))
        self.assertTrue(tab.set_accent((40, 50, 60, 200)))
        record = ribbon._tabs["one"]
        self.assertEqual(tab.accent, (40, 50, 60, 200))
        self.assertEqual(backend.config[record["indicator_line"]]["color"], (40, 50, 60, 200))
        self.assertTrue(tab.set_accent(None))
        self.assertIsNone(tab.accent)
        self.assertEqual(
            backend.config[record["indicator_line"]]["color"],
            ribbon.visual_style.tab_active_border,
        )

    def test_hidden_tab_hides_retained_host(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="modern-clean")
        ribbon.create_tab("home", "Home")
        record = ribbon._tabs["home"]
        self.assertTrue(ribbon.set_tab_visible("home", False))
        self.assertFalse(backend.config[record["host"]]["show"])


    def test_indicator_modes_reuse_retained_primitives(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="modern-clean")
        ribbon.create_tab("home", "Home")
        record = ribbon._tabs["home"]
        identity = (record["host"], record["header"], record["indicator"], record["indicator_line"])

        ribbon.set_render_styles(tab_style="top-line")
        top = backend.config[record["indicator_line"]]
        self.assertLess(top["p1"][1], ribbon.TAB_HEIGHT / 2)

        ribbon.set_render_styles(tab_style="side-accent")
        side = backend.config[record["indicator_line"]]
        self.assertEqual(side["p1"][0], side["p2"][0])
        self.assertNotEqual(side["p1"][1], side["p2"][1])
        self.assertEqual(identity, (record["host"], record["header"], record["indicator"], record["indicator_line"]))

    def test_badge_is_retained_and_runtime_mutable(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="modern-clean")
        tab = ribbon.create_tab("jobs", "Jobs")
        record = ribbon._tabs["jobs"]
        identity = (record["host"], record["header"], record["decoration"], record["badge_bg"], record["badge_text_item"])
        natural_width = record["header_width"]

        self.assertTrue(tab.set_badge(12))
        self.assertEqual(tab.badge, "12")
        self.assertGreater(record["header_width"], natural_width)
        self.assertTrue(backend.config[record["badge_bg"]]["show"])
        self.assertEqual(backend.config[record["badge_text_item"]]["text"], "12")

        self.assertTrue(tab.set_badge(None))
        self.assertIsNone(tab.badge)
        self.assertFalse(backend.config[record["badge_bg"]]["show"])
        self.assertEqual(identity, (record["host"], record["header"], record["decoration"], record["badge_bg"], record["badge_text_item"]))

    def test_context_group_gates_tab_visibility_without_losing_manual_state(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="modern-clean")
        home = ribbon.create_tab("home", "Home")
        context = ribbon.create_context_group("picture", "Picture Tools", accent=(160, 80, 200))
        contextual = context.create_tab("format", "Format")
        record = ribbon._tabs["format"]

        self.assertFalse(context.visible)
        self.assertFalse(record["visible"])
        self.assertEqual(ribbon.active_tab(), home.key)
        self.assertTrue(context.set_visible(True))
        self.assertTrue(record["visible"])
        self.assertTrue(contextual.set_visible(False))
        self.assertFalse(record["visible"])
        self.assertTrue(context.set_visible(False))
        self.assertTrue(context.set_visible(True))
        self.assertFalse(record["visible"])

    def test_context_accent_updates_retained_band(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="modern-clean")
        ribbon.create_tab("home", "Home")
        context = ribbon.create_context_group("chart", "Chart Tools", accent=(10, 120, 210), visible=True)
        tab = context.create_tab("design", "Design")
        record = ribbon._tabs["design"]

        self.assertEqual(tab.context_key, "chart")
        self.assertTrue(backend.config[record["context_line"]]["show"])
        self.assertEqual(backend.config[record["context_line"]]["color"], (10, 120, 210, 255))
        self.assertTrue(context.set_accent((200, 90, 20)))
        self.assertEqual(backend.config[record["context_line"]]["color"], (200, 90, 20, 255))

    def test_context_detach_restores_normal_tab_visibility(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="modern-clean")
        context = ribbon.create_context_group("selection", "Selection", visible=False)
        tab = context.create_tab("selection-tools", "Selection")
        self.assertFalse(ribbon._tabs[tab.key]["visible"])
        self.assertTrue(tab.set_context(None))
        self.assertIsNone(tab.context_key)
        self.assertTrue(ribbon._tabs[tab.key]["visible"])

    def test_appearance_template_can_be_derived_from_existing_preset(self):
        variant = RibbonAppearanceTemplateFactory.variant(
            "modern-clean",
            key="unit-engineering",
            name="Unit Engineering",
            display_template="dense",
            button_style="outlined",
        )
        self.assertEqual(variant.visual_style, "clean")
        self.assertEqual(variant.tab_style, "underline")
        self.assertEqual(variant.display_template, "dense")
        self.assertEqual(variant.button_style, "outlined")


if __name__ == "__main__":
    unittest.main()
