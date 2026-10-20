from pathlib import Path

from DearUIQt.gui.palette import QtFusionMetrics
from DearUIQt.gui.style import METRICS


def test_win11_button_rounding_contract_is_shared():
    assert METRICS.button_rounding == 5
    assert QtFusionMetrics.BUTTON_ROUNDING == 5


def test_all_user_facing_button_themes_use_shared_button_rounding():
    root = Path(__file__).resolve().parents[1]
    dialog = (root / "DearUIQt/dialogs/theme.py").read_text(encoding="utf-8")
    ribbon = (root / "DearUIQt/ribbon/themes.py").read_text(encoding="utf-8")
    menu_bar = (root / "DearUIQt/widgets/menu_bar.py").read_text(encoding="utf-8")
    dock_manager = (root / "DearUIQt/docking/dock_manager.py").read_text(encoding="utf-8")
    style = (root / "DearUIQt/gui/style.py").read_text(encoding="utf-8")

    assert "m.BUTTON_ROUNDING" in dialog
    assert dialog.count("QtFusionMetrics.BUTTON_ROUNDING") >= 3
    # Ribbon command buttons, image buttons, large-label buttons and tabs.
    assert ribbon.count("QtFusionMetrics.BUTTON_ROUNDING") >= 5
    # Root application menu buttons.
    assert "mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING" in menu_bar
    # Dock-area tabs, active and inactive.
    assert dock_manager.count("mvStyleVar_FrameRounding, QtFusionMetrics.BUTTON_ROUNDING") >= 2
    # QDockWidget float/close controls use the same shared metric through METRICS.
    dock_control = style[style.index("def dock_control_theme"):style.index("def splitter_theme")]
    assert "mvStyleVar_FrameRounding, METRICS.button_rounding" in dock_control


def test_disabled_button_state_does_not_fall_back_to_square_renderer_theme():
    root = Path(__file__).resolve().parents[1]
    style = (root / "DearUIQt/gui/style.py").read_text(encoding="utf-8")
    ribbon = (root / "DearUIQt/ribbon/themes.py").read_text(encoding="utf-8")
    dialog = (root / "DearUIQt/dialogs/theme.py").read_text(encoding="utf-8")

    assert "theme_component(backend.mvButton, enabled_state=not disabled)" in style
    assert "for enabled_state in (True, False):" in style
    assert ribbon.count("enabled_state=not disabled") >= 2
    assert dialog.count("for enabled_state in (True, False):") >= 3
