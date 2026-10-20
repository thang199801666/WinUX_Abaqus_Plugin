from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "DearUIQt" / "qt"
DIALOGS = ROOT / "WinUx" / "dialogs"


def _control_source():
    return "\n".join(
        (WIDGETS / name).read_text(encoding="utf-8")
        for name in ("controls.py", "buttons.py", "editors.py", "containers.py", "selection.py")
    )


def test_imgui_qt_style_is_backend_explicit_and_has_no_secondary_ui_toolkit():
    source = (WIDGETS / "style.py").read_text(encoding="utf-8")
    assert "Dear ImGui" in source
    assert "ImGuiQtPalette" in source
    assert "ImGuiQtMetrics" in source
    assert "tkinter" not in source
    assert "PyQt" not in source
    assert "PySide" not in source


def test_retained_widget_base_exposes_qwidget_like_properties():
    source = (WIDGETS / "widget.py").read_text(encoding="utf-8")
    for token in (
        "def setObjectName", "def objectName", "def setProperty", "def property",
        "def setEnabled", "def isEnabled", "def setVisible", "def isVisible",
        "def setFixedSize", "def setToolTip", "def setFocus", "def hasFocus",
    ):
        assert token in source


def test_canonical_controls_are_imgui_named_with_qt_compatibility_aliases():
    source = _control_source()
    for token in (
        "class ImGuiPushButton", "class ImGuiLineEdit", "class ImGuiCheckBox",
        "QPushButton = ImGuiPushButton", "QLineEdit = ImGuiLineEdit",
        "QCheckBox = ImGuiCheckBox",
    ):
        assert token in source


def test_dialog_single_line_fields_use_direct_imgui_line_edit():
    source = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    block = source.split('def line_edit(self, value="", parent=None, **kwargs):', 1)[1].split(
        "def combo(self, items=(), parent=None, **kwargs):", 1
    )[0]
    assert "ImGuiLineEdit(" in block
    assert "dpg.add_child_window" not in block
    assert "InputText" in block


def test_login_uses_dearuiqt_canonical_controls():
    source = (DIALOGS / "login_form.py").read_text(encoding="utf-8")
    assert "from DearUIQt.qt.combo_box import ImGuiComboBox" in source
    assert "QCheckBox" in source
    assert "ImGuiCheckBox(" not in source


def test_phase2_controls_add_imgui_spinboxes_and_groupbox_without_qt_backend():
    source = _control_source()
    for token in (
        "class ImGuiSpinBox", "class ImGuiDoubleSpinBox", "class ImGuiGroupBox",
        "QSpinBox = ImGuiSpinBox", "QDoubleSpinBox = ImGuiDoubleSpinBox",
        "QGroupBox = ImGuiGroupBox",
    ):
        assert token in source
    assert "PyQt" not in source
    assert "PySide" not in source
    assert "tkinter" not in source


def test_spinbox_uses_one_outer_frame_and_custom_up_down_subcontrols():
    source = _control_source()
    block = source.split("class _ImGuiAbstractSpinBox", 1)[1].split(
        "class ImGuiSpinBox", 1
    )[0]
    assert "add_child_window" in block
    assert "add_input_int" in block
    assert "add_input_float" in block
    assert "def _create_spin_arrow" in block
    assert "backend.draw_triangle(" in block
    assert 'label="^"' not in block
    assert 'label="v"' not in block
    assert '▴' not in block
    assert '▾' not in block
    assert '"step": 0' in block


def test_settings_numeric_fields_use_retained_imgui_spinboxes():
    source = (DIALOGS / "settings_form.py").read_text(encoding="utf-8")
    assert "self.spin_int(" in source
    assert "self.spin_float(" in source
    assert "dpg.add_input_int" not in source
    assert "dpg.add_input_float" not in source


def test_dialog_sections_use_reusable_imgui_groupbox():
    source = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
    block = source.split("def section(self, title, parent=None):", 1)[1].split(
        "def invoke_default", 1
    )[0]
    assert "ImGuiGroupBox(" in block
    assert "dpg.child_window" not in block


def test_editable_combo_exposes_qcombobox_like_property_signal_surface():
    source = (WIDGETS / "combo_box.py").read_text(encoding="utf-8")
    for token in (
        "currentTextChanged = Signal()", "currentIndexChanged = Signal()",
        "activated = Signal()", "editTextChanged = Signal()",
        "currentText = current_text", "currentIndex = current_index",
        "setCurrentText = set_current_text", "setCurrentIndex = set_current_index",
        "def setEditable", "def isEditable", "showPopup = open_popup",
        "hidePopup = close_popup",
    ):
        assert token in source
    assert "tkinter" not in source
    assert "PyQt" not in source
