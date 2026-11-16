"""Tests for generic ribbon chrome styles."""
import unittest

from DearUIQt.ribbon import (
    RibbonBar,
    RibbonVisualStyle,
    RibbonVisualStyleFactory,
    get_ribbon_display_template,
    get_ribbon_visual_style,
    register_ribbon_visual_style,
    ribbon_visual_style_names,
)


class _Context:
    def __init__(self, tag):
        self.tag = tag

    def __enter__(self):
        return self.tag

    def __exit__(self, *_args):
        return False


class _Backend:
    def __init__(self):
        self._next = 100
        self.config = {}
        self.bindings = []

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

    def bind_item_theme(self, tag, theme):
        self.bindings.append((tag, theme))

    def configure_item(self, tag, **kwargs):
        self.config.setdefault(tag, {}).update(kwargs)

    def does_item_exist(self, _tag):
        return True

    def delete_item(self, _tag):
        return None


class RibbonVisualStyleTests(unittest.TestCase):
    def test_builtin_catalog_is_content_agnostic(self):
        names = ribbon_visual_style_names()
        for key in ("classic", "clean", "soft", "flat", "minimal", "high-contrast"):
            self.assertIn(key, names)
        self.assertNotIn("plot", names)
        self.assertNotIn("data-analysis", names)

    def test_display_templates_select_visual_defaults(self):
        self.assertEqual(get_ribbon_display_template("classic").visual_style, "classic")
        self.assertEqual(get_ribbon_display_template("compact").visual_style, "clean")
        self.assertEqual(get_ribbon_display_template("dense").visual_style, "flat")
        self.assertEqual(get_ribbon_display_template("large-icons").visual_style, "soft")
        self.assertEqual(get_ribbon_display_template("minimal").visual_style, "minimal")

    def test_style_catalog_has_meaningfully_different_chrome(self):
        classic = get_ribbon_visual_style("classic")
        soft = get_ribbon_visual_style("soft")
        minimal = get_ribbon_visual_style("minimal")
        self.assertNotEqual(classic.tab_active_border, soft.tab_active_border)
        self.assertGreater(soft.group_border_size, classic.group_border_size)
        self.assertEqual(minimal.body_border_size, 0)

    def test_custom_style_can_be_registered(self):
        custom = RibbonVisualStyle(
            key="unit-test-style",
            name="Unit Test",
            tab_active=(1, 2, 3, 255),
            button_rounding=7,
        )
        register_ribbon_visual_style(custom, replace=True)
        self.assertIs(RibbonVisualStyleFactory.get("unit-test-style"), custom)

    def test_rgb_colors_are_normalized_to_rgba(self):
        custom = RibbonVisualStyle(key="rgb-test", name="RGB", body_bg=(1, 2, 3))
        self.assertEqual(custom.body_bg, (1, 2, 3, 255))

    def test_runtime_style_switch_preserves_widget_identity(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, display_template="compact")
        tab = ribbon.create_tab("home", "Home")
        group = tab.add_group("tools", "Tools", width=180)
        button = group.add_button("run", "Run")
        tab_tag = ribbon._tabs["home"]["header"]
        group_tag = ribbon._groups[("home", "tools")]["tag"]
        command_tag = ribbon._buttons["run"]["tag"]

        style = ribbon.set_visual_style("high-contrast")

        self.assertEqual(style.key, "high-contrast")
        self.assertEqual(ribbon.visual_style_key, "high-contrast")
        self.assertEqual(ribbon._tabs["home"]["header"], tab_tag)
        self.assertEqual(ribbon._groups[("home", "tools")]["tag"], group_tag)
        self.assertEqual(ribbon._buttons["run"]["tag"], command_tag)
        self.assertEqual(button.key, "run")

    def test_explicit_style_overrides_display_default(self):
        ribbon = RibbonBar(1, backend=_Backend(), display_template="dense", visual_style="soft")
        self.assertEqual(ribbon.display_template_key, "dense")
        self.assertEqual(ribbon.visual_style_key, "soft")


if __name__ == "__main__":
    unittest.main()
