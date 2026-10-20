from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]


def _source(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def _dpg_calls(source):
    tree = ast.parse(source)
    return sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "dpg"
        for node in ast.walk(tree)
    )


def test_job_plots_uses_dearuiqt_plot_and_dock_widget_contracts():
    source = _source("WinUx/ui/components/job_plots.py")
    assert "QPlotWidget" in source
    assert "QPlotAxis" in source
    assert "QLineSeries" in source
    assert "contentWidget()" in source
    assert "dragHandleWidget()" in source
    for raw in ("dpg.add_plot(", "dpg.add_plot_axis(", "dpg.add_line_series(",
                "dpg.fit_axis_data(", "dpg.mvPlotCol_", "dpg.mvPlotStyleVar_"):
        assert raw not in source
    assert _dpg_calls(source) <= 30


def test_floating_runtime_delegates_context_viewport_and_frame_lifecycle():
    source = _source("WinUx/ui/hosting/floating_runtime.py")
    assert "QGuiRuntime" in source
    for raw in ("dpg.create_context(", "dpg.create_viewport(", "dpg.configure_viewport(",
                "dpg.setup_dearpygui(", "dpg.show_viewport(",
                "dpg.render_dearpygui_frame(", "dpg.destroy_context("):
        assert raw not in source
    assert _dpg_calls(source) <= 22


def test_plot_digitizer_value_and_visibility_state_use_qtdialog_control_api():
    source = _source("WinUx/plotdigitizer/ui/dialog.py")
    assert "self.control_value(" in source
    assert "self.set_control_value(" in source
    assert "self.set_control_visible(" in source
    assert "self.set_control_items(" in source
    assert "dpg.get_value(" not in source
    assert "dpg.set_value(" not in source
    assert _dpg_calls(source) <= 75


def test_r86_global_backend_boundary_continues_toward_pure_dearuiqt():
    calls = 0
    files = 0
    direct_imports = []
    for path in (ROOT / "WinUx").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        count = _dpg_calls(source)
        if count:
            calls += count
            files += 1
        if re.search(r"^\s*(?:from|import)\s+dearpygui\b", source, re.MULTILINE):
            direct_imports.append(path)
    assert direct_imports == []
    assert calls <= 1340
    assert files <= 51


def test_qtdialog_control_value_prioritizes_checkbox_state_over_caption():
    source = _source("DearUIQt/dialogs/qt_dialog.py")
    priority = '("isChecked", "currentText", "value", "toPlainText", "text")'
    assert priority in source


def test_qtdialog_control_value_returns_checkbox_state_not_checkbox_caption():
    from DearUIQt.dialogs.qt_dialog import QtDialog

    class CheckBoxLike:
        tag = 41
        def isChecked(self): return False
        def text(self): return "Enabled"

    dialog = object.__new__(QtDialog)
    dialog._control_wrappers = {41: CheckBoxLike()}
    assert dialog.control_value(41) is False
