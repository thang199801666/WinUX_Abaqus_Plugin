"""Static regressions for the shared Dear ImGui QDialog behaviour contract."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIALOG = (ROOT / "WinUx" / "dialogs" / "qt_dialog.py").read_text(encoding="utf-8")
CONTROLS = (ROOT / "WinUx" / "widgets" / "controls.py").read_text(encoding="utf-8")


def test_qdialog_has_qt_accept_reject_and_numpad_enter_contract():
    assert "def accept(self):" in DIALOG
    assert "def reject(self):" in DIALOG
    assert 'getattr(dpg, "mvKey_NumPadEnter", None)' in DIALOG
    assert "register_escape_target(self.tag, self.reject)" in DIALOG
    assert "on_close=lambda: self.reject()" in DIALOG


def test_qdialog_focuses_first_child_and_restores_launching_control():
    assert "self._focus_restore_item = dpg.get_focused_item() or None" in DIALOG
    assert "def set_initial_focus(self, item):" in DIALOG
    assert "def _focus_initial(self):" in DIALOG
    assert "self.view.after(0, self._focus_initial)" in DIALOG
    assert "self._item_belongs_to(target, parent.tag)" in DIALOG
    assert "dpg.focus_item(target)" in DIALOG


def test_return_matches_qpushbutton_autodefault_and_editor_ownership():
    assert "QPushButton::autoDefault semantics" in DIALOG
    assert "isinstance(wrapper, QPushButton)" in DIALOG
    assert "wrapper.click()" in DIALOG
    assert "self.enter_editors.add(item)" in DIALOG
    assert "if table.hasFocus():" in DIALOG


def test_button_box_registers_primary_default_and_reject_action():
    assert '_DIALOG_REJECT_CAPTIONS = {"cancel", "close", "dismiss", "no"}' in DIALOG
    assert 'str(role or "secondary").lower() == "primary"' in DIALOG
    assert "widget.setDefault(True)" in DIALOG
    assert "self._reject, self._reject_button = callback, button" in DIALOG


def test_qpushbutton_exposes_programmatic_click_like_qt():
    assert "def click(self):" in CONTROLS
    assert "matching QPushButton::click()" in CONTROLS
    assert "self.clicked.emit()" in CONTROLS
