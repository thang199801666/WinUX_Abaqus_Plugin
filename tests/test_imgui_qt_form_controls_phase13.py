from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_radio_group_is_retained_native_dear_imgui_control():
    style = _read("widgets/imgui_qt_style.py")
    controls = _read("widgets/controls.py")
    assert "def radio_group_theme(backend, *, disabled=False, focused=False)" in style
    assert "class ImGuiRadioButtonGroup(QWidget)" in controls
    assert "backend.add_radio_button(" in controls
    assert "self.currentTextChanged = Signal()" in controls
    assert "self.currentIndexChanged = Signal()" in controls
    assert "self.activated = Signal()" in controls
    assert "focus_item(self.tag)" not in controls.split(
        "class ImGuiRadioButtonGroup", 1)[1].split(
        "# Qt-style names remain compatibility aliases", 1)[0]


def test_qtdialog_exposes_retained_checkbox_radio_and_progress_factories():
    dialog = _read("dialogs/qt_dialog.py")
    assert "def checkbox(self, text=\"\", *, checked=False, parent=None):" in dialog
    assert "def radio_group(self, items=(), *, current=None, horizontal=False," in dialog
    assert "def progress_bar(self, value=0.0, *, parent=None, overlay=None):" in dialog
    assert "self._control_wrappers[widget.tag] = widget" in dialog


def test_job_edit_and_manager_use_retained_form_controls():
    edit = _read("dialogs/job_edit_form.py")
    manager = _read("dialogs/job_manager_form.py")
    assert "self.radio_group(" in edit
    assert "dpg.add_radio_button" not in edit
    assert 'row = {"run": self.checkbox(checked=True)}' in manager
    assert 'row["overwrite"] = self.checkbox(' in manager
    assert "dpg.add_checkbox" not in manager


def test_transfer_center_uses_shared_progress_and_button_state_contracts():
    source = _read("dialogs/transfer_center_form.py")
    assert "self.progress_bar(" in source
    assert "action = self.action(" in source
    assert 'self.set_control_enabled(row["action"]' in source
    assert "dpg.add_progress_bar" not in source
    assert "dpg.add_button(" not in source


def test_phase13_production_paths_remain_dear_imgui_only():
    source = "\n".join([
        _read("widgets/imgui_qt_style.py"),
        _read("widgets/controls.py"),
        _read("dialogs/qt_dialog.py"),
        _read("dialogs/job_edit_form.py"),
        _read("dialogs/job_manager_form.py"),
        _read("dialogs/transfer_center_form.py"),
    ])
    for forbidden in ("import tkinter", "from tkinter", "PyQt6", "PySide6"):
        assert forbidden not in source
