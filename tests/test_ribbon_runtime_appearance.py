"""Runtime display/appearance switching and generic gallery tests."""
import unittest

from DearUIQt.ribbon import RibbonAppearanceGallery, RibbonBar


class _Context:
    def __init__(self, tag): self.tag = tag
    def __enter__(self): return self.tag
    def __exit__(self, *_args): return False


class _Backend:
    def __init__(self):
        self._next = 100
        self.config = {}
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
    def add_image_button(self, *_args, **_kwargs): return self._id()
    def add_text(self, *_args, **_kwargs): return self._id()
    def add_spacer(self, **_kwargs): return self._id()
    def add_drawlist(self, **_kwargs): return self._id()
    def draw_line(self, p1, p2, **kwargs):
        tag = self._id(); self.lines[tag] = {"p1": p1, "p2": p2, **kwargs}; return tag
    def draw_rectangle(self, pmin, pmax, **kwargs):
        tag = self._id(); self.rects[tag] = {"pmin": pmin, "pmax": pmax, **kwargs}; return tag
    def draw_text(self, pos, text, **kwargs):
        tag = self._id(); self.texts[tag] = {"pos": pos, "text": text, **kwargs}; return tag
    def bind_item_theme(self, *_args, **_kwargs): return None
    def configure_item(self, tag, **kwargs): self.config.setdefault(tag, {}).update(kwargs)
    def does_item_exist(self, _tag): return True
    def delete_item(self, _tag): return None


class RibbonRuntimeAppearanceTests(unittest.TestCase):
    def _build(self):
        backend = _Backend()
        ribbon = RibbonBar(1, backend=backend, appearance_template="classic-office")
        home = ribbon.create_tab("home", "Home", badge=2)
        ctx = ribbon.create_context_group("selection", "Selection", accent=(120, 60, 200), visible=True)
        contextual = ctx.create_tab("format", "Format")
        group = home.add_group("tools", "Tools", width=120, layout="mixed")
        default = group.add_button("default", "Default", size="large", checkable=True, checked=True)
        custom = group.add_button("custom", "Custom", size="small", width=137)
        return backend, ribbon, home, contextual, group, default, custom

    def test_runtime_appearance_switch_preserves_widget_identity_and_state(self):
        backend, ribbon, home, contextual, group, default, custom = self._build()
        identity = (
            ribbon._tabs["home"]["host"], ribbon._tabs["home"]["header"],
            ribbon._groups[("home", "tools")]["tag"],
            ribbon._buttons["default"]["tag"], ribbon._buttons["custom"]["tag"],
        )

        result = ribbon.set_appearance_template("touch-soft")

        self.assertEqual(result["appearance_template"], "touch-soft")
        self.assertEqual(ribbon.display_template_key, "touch")
        self.assertEqual(ribbon.visual_style_key, "soft")
        self.assertTrue(default.is_checked())
        self.assertEqual(home.badge, "2")
        self.assertEqual(contextual.context_key, "selection")
        self.assertEqual(identity, (
            ribbon._tabs["home"]["host"], ribbon._tabs["home"]["header"],
            ribbon._groups[("home", "tools")]["tag"],
            ribbon._buttons["default"]["tag"], ribbon._buttons["custom"]["tag"],
        ))
        self.assertEqual(
            backend.config[ribbon._tabs["home"]["host"]]["height"], ribbon.TAB_HEIGHT)
        self.assertEqual(
            backend.config[ribbon._buttons["default"]["tag"]]["height"], ribbon.LARGE_BUTTON_HEIGHT)

    def test_default_width_tracks_template_but_explicit_width_is_retained(self):
        backend, ribbon, *_ = self._build()
        default_tag = ribbon._buttons["default"]["tag"]
        custom_tag = ribbon._buttons["custom"]["tag"]

        ribbon.set_display_template("dense")

        self.assertEqual(ribbon._buttons["default"]["width"], ribbon.LARGE_BUTTON_WIDTH)
        self.assertEqual(backend.config[default_tag]["width"], ribbon.LARGE_BUTTON_WIDTH)
        self.assertEqual(ribbon._buttons["custom"]["width"], 137)
        self.assertEqual(backend.config[custom_tag]["width"], 137)

    def test_runtime_switch_updates_body_group_and_separator_geometry(self):
        backend, ribbon, *_ = self._build()
        group = ribbon._groups[("home", "tools")]
        ribbon.set_display_template("compact")
        self.assertEqual(backend.config[ribbon.body]["height"], ribbon.BODY_HEIGHT)
        self.assertEqual(backend.config[group["tag"]]["height"], ribbon.BODY_HEIGHT - 10)
        self.assertEqual(backend.config[group["separator"]]["width"], ribbon.GROUP_SEPARATOR_WIDTH)
        self.assertEqual(backend.config[group["separator"]]["height"], ribbon.BODY_HEIGHT - 12)

    def test_responsive_override_survives_template_switch(self):
        _, ribbon, *_ = self._build()
        ribbon.set_responsive(True, width=420, adaptive=False)
        self.assertFalse(ribbon._adaptive_responsive)
        ribbon.set_display_template("touch")
        self.assertFalse(ribbon._adaptive_responsive)

        ribbon.set_responsive(True, width=420, adaptive=None)
        self.assertTrue(ribbon._adaptive_responsive)
        ribbon.set_display_template("dense")
        self.assertTrue(ribbon._adaptive_responsive)

    def test_runtime_appearance_override_axes(self):
        _, ribbon, *_ = self._build()
        state = ribbon.set_appearance_template(
            "modern-clean", display_template="dense", visual_style="soft",
            tab_style="pill", group_style="card", button_style="raised")
        self.assertEqual(state["appearance_template"], "modern-clean")
        self.assertEqual(state["display_template"], "dense")
        self.assertEqual(state["visual_style"], "soft")
        self.assertEqual(state["tab_style"], "pill")
        self.assertEqual(state["group_style"], "card")
        self.assertEqual(state["button_style"], "raised")

    def test_gallery_catalog_is_content_independent_and_can_restore_snapshot(self):
        _, ribbon, *_ = self._build()
        gallery = RibbonAppearanceGallery(["modern-clean", "dense-outline", "touch-soft"])
        self.assertEqual(gallery.names(), ("modern-clean", "dense-outline", "touch-soft"))
        preview = gallery.get("dense-outline")
        self.assertEqual(preview.display_template, "dense")
        self.assertEqual(preview.button_style, "outlined")

        snapshot = gallery.snapshot(ribbon)
        gallery.apply(ribbon, "touch-soft")
        self.assertEqual(ribbon.appearance_template_key, "touch-soft")
        gallery.restore(ribbon, snapshot)
        self.assertEqual(ribbon.display_template_key, snapshot.display_template)
        self.assertEqual(ribbon.visual_style_key, snapshot.visual_style)
        self.assertEqual(ribbon.tab_render_style, snapshot.tab_style)

    def test_gallery_view_uses_miniature_draw_preview_without_nested_ribbons(self):
        backend, ribbon, *_ = self._build()
        gallery = RibbonAppearanceGallery(["modern-clean", "touch-soft"])
        before_tabs = tuple(ribbon._tabs)
        view = gallery.create_view(999, ribbon, card_width=180, preview_height=60)
        self.assertEqual(set(view.cards), {"modern-clean", "touch-soft"})
        self.assertEqual(tuple(ribbon._tabs), before_tabs)
        self.assertTrue(backend.rects)  # miniature preview primitives were drawn
        self.assertTrue(backend.lines)


if __name__ == "__main__":
    unittest.main()
