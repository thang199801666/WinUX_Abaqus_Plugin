"""M6n dialog focus-handoff and close-gesture regression contracts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_focus_restore_uses_generation_token():
    source = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text()
    assert "self._focus_restore_generation = 0" in source
    assert "generation != self._focus_restore_generation" in source
    assert "self.view.after(0, self._restore_embedded_owner_focus, generation)" in source
    assert "if self.isVisible():" in source


def test_new_active_window_supersedes_stale_focus_return():
    source = (ROOT / "DearUIQt" / "dialogs" / "qt_dialog.py").read_text()
    block = source[source.index("def _restore_embedded_owner_focus"):
                   source.index("def delete_owned_item") ]
    assert "active_now = application.activeWindow()" in block
    assert "active_now is not self" in block
    assert "active_now is parent" in block
    assert "closing an old dialog must not" in block

def test_popup_close_consumes_pointer_gesture():
    source = (ROOT / "DearUIQt" / "widgets" / "menu.py").read_text()
    assert "root.hide(consume_pointer=True)" in source
    assert "release_popup_input(self, consume_gesture=bool(consume_pointer))" in source
