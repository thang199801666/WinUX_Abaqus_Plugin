from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "WinUx" / "components" / "interaction_gate.py"
EXPLORER = ROOT / "WinUx" / "components" / "explorer_list_view.py"
EXPLORER_CONTEXT = ROOT / "WinUx" / "components" / "explorer_context_menu.py"
EXPLORER_POINTER = ROOT / "WinUx" / "components" / "explorer_pointer_capture.py"
EXPLORER_DISPATCH = ROOT / "WinUx" / "components" / "explorer_pointer_dispatch.py"
EXPLORER_HIT = ROOT / "WinUx" / "components" / "explorer_hit_testing.py"
EXPLORER_RENDER = ROOT / "WinUx" / "components" / "explorer_rendering.py"
DOCK = ROOT / "WinUx" / "components" / "dock_widget.py"
TOOLBAR = ROOT / "WinUx" / "components" / "toolbar.py"
COMBO = ROOT / "WinUx" / "components" / "qt_combo_box.py"
RENAME = ROOT / "WinUx" / "components" / "explorer_rename_textbox.py"
VIEW = ROOT / "WinUx" / "view.py"
SPLITTER_LAYOUT = ROOT / "WinUx" / "ui" / "splitter_layout.py"
VIEW_RUNTIME_SOURCE = VIEW.read_text(encoding="utf-8") + "\n" + SPLITTER_LAYOUT.read_text(encoding="utf-8")


class PointerSurfaceGateRegressionTests(unittest.TestCase):
    def test_gate_uses_screen_rect_and_release_latch(self):
        source = GATE.read_text(encoding="utf-8")
        self.assertIn("get_item_rect_min", source)
        self.assertIn("_surface_press_item", source)
        self.assertIn("_release_guard_until_frame", source)
        self.assertIn("Also block hover and click callbacks", source)

    def test_docked_root_does_not_globally_block_sibling_panes(self):
        source = DOCK.read_text(encoding="utf-8")
        # Only the tear-off handle is protected while embedded. The host
        # protects the real top-level floating window after detaching.
        self.assertNotIn("register_pointer_protected_item(self.root)", source)
        self.assertIn("register_pointer_protected_item(self.drag_handle)", source)
        self.assertIn('unregister_pointer_protected_item(getattr(self, \"root\", None))', source)

    def test_explorer_blocks_left_right_drag_hover_behind_surfaces(self):
        source = EXPLORER.read_text(encoding="utf-8")
        dispatch = EXPLORER_DISPATCH.read_text(encoding="utf-8")
        rendering = EXPLORER_RENDER.read_text(encoding="utf-8")
        context = EXPLORER_CONTEXT.read_text(encoding="utf-8")
        self.assertGreaterEqual((source + dispatch + rendering).count("if pointer_input_is_blocked(self):"), 5)
        self.assertIn("register_pointer_protected_item(self.itemmenu_tag)", context)
        self.assertIn("register_pointer_protected_item(submenu_tag)", context)


    def test_explicit_capture_is_owner_aware_for_widget_gestures(self):
        gate = GATE.read_text(encoding="utf-8")
        explorer = EXPLORER.read_text(encoding="utf-8")
        dispatch = EXPLORER_DISPATCH.read_text(encoding="utf-8")
        pointer = EXPLORER_POINTER.read_text(encoding="utf-8")
        self.assertIn("def pointer_input_is_blocked(owner=None):", gate)
        self.assertIn("return _pointer_owner is not owner", gate)
        self.assertIn("acquire_pointer_input(self)", pointer)
        self.assertIn("release_pointer_input(self)", pointer)
        self.assertIn("self._header_gesture = True", dispatch)
        self.assertIn("if self._header_gesture and self._resize_key is None:", dispatch)

    def test_popup_widgets_are_input_surfaces(self):
        toolbar = TOOLBAR.read_text(encoding="utf-8")
        combo = COMBO.read_text(encoding="utf-8")
        rename = RENAME.read_text(encoding="utf-8")
        self.assertIn("register_pointer_protected_item(popup)", toolbar)
        # The editable combo is now a pure Dear ImGui composite rather than
        # dpg.add_combo(). Its custom popup must explicitly participate in the
        # global pointer-surface gate to prevent click-through.
        self.assertNotIn("dpg.add_combo(", combo)
        self.assertIn("dpg.add_window(", combo)
        self.assertIn("register_pointer_protected_item(self._popup)", combo)
        self.assertIn("unregister_pointer_protected_item(self._popup)", combo)
        self.assertIn("register_pointer_protected_item(self.window_tag)", rename)

    def test_job_header_has_priority_over_outer_horizontal_splitter(self):
        hit_testing = EXPLORER_HIT.read_text(encoding="utf-8")
        view = VIEW_RUNTIME_SOURCE
        self.assertIn("def header_pointer_hit_test(self, separator_only=False):", hit_testing)
        self.assertIn("def _job_view_header_owns_pointer(self, separator_only=False):", view)
        self.assertIn("if self._job_view_header_owns_pointer():\n            return", view)
        self.assertIn("not getattr(self, \"_horizontal_splitter_dragging\", False)", view)
        self.assertIn("and self._job_view_header_owns_pointer()", view)



if __name__ == "__main__":
    unittest.main()
