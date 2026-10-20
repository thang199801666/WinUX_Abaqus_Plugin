from pathlib import Path


def test_right_click_is_routed_outside_dpg_global_mouse_handler():
    source = Path("WinUx/dialogs/console_form.py").read_text(encoding="utf-8")
    assert "def native_right_click(self, x, y):" in source
    assert "self.view.after(0, lambda: self._show_context_menu_deferred(int(x), int(y)))" in source
    assert "button=dpg.mvMouseButton_Right, callback=self._right_click" not in source
    assert ".popup(" not in source[source.index("    def _create_context_menu("):source.index("    def _menu_action(")]
