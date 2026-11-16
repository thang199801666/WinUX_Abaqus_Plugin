"""Tests for ready-made, content-independent Ribbon appearance templates."""
import unittest

from DearUIQt.ribbon import (
    RibbonAppearanceTemplate,
    RibbonAppearanceTemplateFactory,
    RibbonBar,
    get_ribbon_appearance_template,
    register_ribbon_appearance_template,
    ribbon_appearance_template_names,
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
        self.theme_colors = []
        self.theme_styles = []
    def _id(self):
        self._next += 1
        return self._next
    def __getattr__(self, name):
        if name.startswith("mv"):
            return name
        raise AttributeError(name)
    def theme(self): return _Context(self._id())
    def theme_component(self, *_args, **_kwargs): return _Context(self._id())
    def add_theme_color(self, *args, **kwargs):
        self.theme_colors.append((args, kwargs)); return self._id()
    def add_theme_style(self, *args, **kwargs):
        self.theme_styles.append((args, kwargs)); return self._id()
    def add_child_window(self, **_kwargs): return self._id()
    def add_group(self, **_kwargs): return self._id()
    def add_button(self, **_kwargs): return self._id()
    def add_text(self, *_args, **_kwargs): return self._id()
    def add_spacer(self, **_kwargs): return self._id()
    def add_drawlist(self, **_kwargs): return self._id()
    def draw_line(self, *_args, **_kwargs): return self._id()
    def bind_item_theme(self, tag, theme): self.bindings.append((tag, theme))
    def configure_item(self, tag, **kwargs): self.config.setdefault(tag, {}).update(kwargs)
    def does_item_exist(self, _tag): return True
    def delete_item(self, _tag): return None


class RibbonAppearanceTemplateTests(unittest.TestCase):
    def test_builtin_catalog_is_generic(self):
        names = ribbon_appearance_template_names()
        for key in (
            "classic-office", "modern-clean", "soft-card", "compact-flat",
            "dense-outline", "touch-soft", "minimal", "high-contrast",
            "topline-clean", "side-accent-dense",
        ):
            self.assertIn(key, names)
        self.assertNotIn("plot-workbench", names)
        self.assertNotIn("data-analysis", names)

    def test_templates_combine_all_visual_layers(self):
        soft = get_ribbon_appearance_template("soft-card")
        dense = get_ribbon_appearance_template("dense-outline")
        self.assertEqual((soft.tab_style, soft.group_style, soft.button_style), ("pill", "card", "raised"))
        self.assertEqual((dense.tab_style, dense.group_style, dense.button_style), ("underline", "bordered", "outlined"))
        self.assertNotEqual(soft.display_template, dense.display_template)


    def test_indicator_presets_use_retained_modes(self):
        top = get_ribbon_appearance_template("topline-clean")
        side = get_ribbon_appearance_template("side-accent-dense")
        self.assertEqual(top.tab_style, "top-line")
        self.assertEqual(side.tab_style, "side-accent")
        self.assertEqual(side.display_template, "dense")

    def test_factory_create_applies_template_without_content(self):
        ribbon = RibbonAppearanceTemplateFactory.create(1, "soft-card", backend=_Backend())
        self.assertEqual(ribbon.appearance_template_key, "soft-card")
        self.assertEqual(ribbon.display_template_key, "balanced")
        self.assertEqual(ribbon.visual_style_key, "soft")
        self.assertEqual(ribbon.tab_render_style, "pill")
        self.assertEqual(ribbon.group_render_style, "card")
        self.assertEqual(ribbon.button_render_style, "raised")
        self.assertEqual(ribbon._tabs, {})

    def test_explicit_axes_override_appearance_defaults(self):
        ribbon = RibbonBar(
            1, backend=_Backend(), appearance_template="soft-card",
            display_template="compact", visual_style="flat",
            tab_style="underline", group_style="flat", button_style="outlined",
        )
        self.assertEqual(ribbon.display_template_key, "compact")
        self.assertEqual(ribbon.visual_style_key, "flat")
        self.assertEqual(ribbon.tab_render_style, "underline")
        self.assertEqual(ribbon.group_render_style, "flat")
        self.assertEqual(ribbon.button_render_style, "outlined")

    def test_custom_template_can_be_registered(self):
        custom = RibbonAppearanceTemplate(
            key="unit-appearance", name="Unit Appearance",
            display_template="compact", visual_style="clean",
            tab_style="pill", group_style="bordered", button_style="flat",
        )
        register_ribbon_appearance_template(custom, replace=True)
        self.assertIs(RibbonAppearanceTemplateFactory.get("unit-appearance"), custom)

    def test_invalid_render_modes_fail_early(self):
        with self.assertRaises(ValueError):
            RibbonAppearanceTemplate(key="bad-mode", name="Bad", tab_style="unknown")

    def test_runtime_render_switch_preserves_widget_identity(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="classic-office")
        tab = ribbon.create_tab("home", "Home")
        group = tab.add_group("tools", "Tools", width=180)
        button = group.add_button("run", "Run")
        tab_tag = ribbon._tabs["home"]["header"]
        group_tag = ribbon._groups[("home", "tools")]["tag"]
        button_tag = ribbon._buttons["run"]["tag"]

        result = ribbon.set_render_styles(
            tab_style="pill", group_style="card", button_style="outlined")

        self.assertEqual(result["tab_style"], "pill")
        self.assertEqual(ribbon._tabs["home"]["header"], tab_tag)
        self.assertEqual(ribbon._groups[("home", "tools")]["tag"], group_tag)
        self.assertEqual(ribbon._buttons["run"]["tag"], button_tag)
        self.assertEqual(button.key, "run")

    def test_non_separator_group_style_hides_separator(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="classic-office")
        tab = ribbon.create_tab("home", "Home")
        tab.add_group("tools", "Tools", width=180)
        separator = ribbon._groups[("home", "tools")]["separator"]

        ribbon.set_render_styles(group_style="card")
        self.assertFalse(backend.config[separator]["show"])
        ribbon.set_render_styles(group_style="separator")
        self.assertTrue(backend.config[separator]["show"])


if __name__ == "__main__":
    unittest.main()
