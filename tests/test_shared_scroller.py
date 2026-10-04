from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SharedScrollerTests(unittest.TestCase):
    def test_shared_scroller_is_backend_neutral_and_has_one_geometry_contract(self):
        source = (ROOT / "WinUx" / "components" / "shared_scroller.py").read_text(encoding="utf-8")
        self.assertIn("class SharedScrollerMetrics", source)
        self.assertIn("THICKNESS = 11", source)
        self.assertIn("HIT_THICKNESS = 19", source)
        self.assertIn("COLLAPSED_THICKNESS = 6", source)
        self.assertIn("class SharedScrollerPalette", source)
        self.assertNotIn("import dearpygui", source)

    def test_all_primary_dpg_surfaces_use_shared_scroller_helper(self):
        for relative in (
            "WinUx/components/explorer_list_view.py",
            "WinUx/dialogs/theme.py",
            "WinUx/dialogs/console_form.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("add_dpg_scroller_style", source, relative)

    def test_native_dialogs_and_notepad_use_shared_ttk_scroller(self):
        modern = (ROOT / "WinUx" / "dialogs" / "modern.py").read_text(encoding="utf-8")
        notepad = (ROOT / "WinUx" / "services" / "server_notepad_process.py").read_text(encoding="utf-8")
        notepad += "\n" + (ROOT / "WinUx" / "services" / "server_notepad_editor.py").read_text(encoding="utf-8")
        notepad += "\n" + (ROOT / "WinUx" / "services" / "server_notepad_layout.py").read_text(encoding="utf-8")
        self.assertIn("configure_ttk_scroller_styles(style)", modern)
        self.assertIn("make_ttk_scroller", modern)
        self.assertIn("configure_ttk_scroller_styles(style)", notepad)
        self.assertIn("make_ttk_scroller(ttk, editor_area", notepad)

    def test_old_per_surface_scrollbar_colours_are_not_bound_in_primary_dpg_themes(self):
        components = ROOT / "WinUx" / "components"
        explorer = (components / "explorer_list_view.py").read_text(encoding="utf-8")
        explorer += "\n" + (components / "explorer_layout.py").read_text(encoding="utf-8")
        dialogs = (ROOT / "WinUx" / "dialogs" / "theme.py").read_text(encoding="utf-8")
        console = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
        self.assertNotIn('dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, cfg["scrollbar_grab"])', explorer)
        self.assertNotIn("dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, p.BORDER_LIGHT)", dialogs)
        self.assertNotIn("dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, SCROLLBAR)", console)

    def test_dpg_primary_surfaces_use_shared_arrow_endcap_overlay(self):
        shared = (ROOT / "WinUx" / "components" / "shared_scroller.py").read_text(encoding="utf-8")
        components = ROOT / "WinUx" / "components"
        explorer = (components / "explorer_list_view.py").read_text(encoding="utf-8")
        explorer += "\n" + (components / "explorer_layout.py").read_text(encoding="utf-8")
        console = (ROOT / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
        self.assertIn("class DpgScrollerArrowOverlay", shared)
        self.assertIn("ARROW_BUTTON_EXTENT = 11", shared)
        self.assertIn("DpgScrollerArrowOverlay", explorer)
        self.assertIn("DpgScrollerArrowOverlay", console)
        self.assertIn('direction == "up"', shared)
        self.assertIn('direction == "down"', shared)
        self.assertIn('direction == "left"', shared)

    def test_dpg_arrow_overlay_uses_reliable_child_window_geometry(self):
        shared = (ROOT / "WinUx" / "components" / "shared_scroller.py").read_text(encoding="utf-8")
        components = ROOT / "WinUx" / "components"
        explorer = (components / "explorer_list_view.py").read_text(encoding="utf-8")
        explorer += "\n" + (components / "explorer_layout.py").read_text(encoding="utf-8")
        self.assertIn("rect_provider=None", shared)
        self.assertIn("def _target_rect(self):", shared)
        self.assertIn("dpg.get_item_children(self.target_item, 1)", shared)
        self.assertIn("rect_provider=self._body_viewport_rect", explorer)
        self.assertIn("overlay.update()", explorer)

    def test_dpg_scrollbar_skin_draws_track_thumb_buttons_and_corner(self):
        shared = (ROOT / "WinUx" / "components" / "shared_scroller.py").read_text(encoding="utf-8")
        self.assertIn('"v_track", "v_thumb", "h_track", "h_thumb", "corner"', shared)
        self.assertIn('self._set_part("v_track"', shared)
        self.assertIn('self._set_part("v_thumb"', shared)
        self.assertIn('self._set_part("h_track"', shared)
        self.assertIn('self._set_part("h_thumb"', shared)
        self.assertIn('self._set_part("corner"', shared)

    def test_listview_scroller_geometry_is_clamped_to_real_pane(self):
        hit_testing = (ROOT / "WinUx" / "components" / "explorer_hit_testing.py").read_text(encoding="utf-8")
        self.assertIn('pane = self._safe_item_rect(self.window_tag)', hit_testing)
        self.assertIn('vx0, vx1 = max(vx0, px0), min(vx1, px1)', hit_testing)
        self.assertIn('body_y0 = max(body_y0, float(pinned[3]))', hit_testing)

    def test_dpg_scroller_keeps_native_gutter_with_hover_animation(self):
        shared = (ROOT / "WinUx" / "components" / "shared_scroller.py").read_text(encoding="utf-8")
        self.assertIn("ARROW_BUTTON_EXTENT = 11", shared)
        self.assertIn("native_t = float(m.THICKNESS)", shared)
        self.assertIn("m.HOVER_DURATION", shared)
        for direction in ("up", "down", "left", "right"):
            self.assertIn('"{}"'.format(direction), shared)



if __name__ == "__main__":
    unittest.main()
