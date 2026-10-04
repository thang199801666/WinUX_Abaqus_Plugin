from pathlib import Path

from WinUx.widgets import ImGuiTabWidget, QTabWidget, ImGuiMenu, QMenu
from WinUx.widgets.menu import _normalize_action

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "WinUx" / "widgets"


def test_tab_and_menu_contracts_are_dear_imgui_only():
    for name in ("tabs.py", "menu.py"):
        source = (WIDGETS / name).read_text(encoding="utf-8")
        assert "tkinter" not in source
        assert "PyQt" not in source
        assert "PySide" not in source
        assert "Dear" in source


def test_tab_widget_and_menu_keep_qt_style_aliases_only():
    assert QTabWidget is ImGuiTabWidget
    assert QMenu is ImGuiMenu


def test_menu_spec_normalizes_nested_checkable_actions():
    item = _normalize_action({
        "id": "plots",
        "label": "Plots",
        "checkable": True,
        "checked": True,
        "children": [("Open", "open")],
    })
    assert item["id"] == "plots"
    assert item["checkable"] is True
    assert item["checked"] is True
    assert item["children"][0]["action"] == "open"


def test_item_views_use_strong_selected_row_theme_and_shared_imgui_menu():
    source = (WIDGETS / "item_views.py").read_text(encoding="utf-8")
    assert "def qt_item_row_theme" in source
    assert "p.HIGHLIGHT_TEXT" in source
    assert "self._context_menu = ImGuiMenu(" in source
    assert "setActionEnabled" in source
    assert "setActionChecked" in source


def test_tab_widget_exposes_qtabwidget_like_surface():
    source = (WIDGETS / "tabs.py").read_text(encoding="utf-8")
    for token in (
        "class ImGuiTabWidget", "currentChanged = Signal()", "def addTab",
        "def currentIndex", "def setCurrentIndex", "def removeTab",
        "QTabWidget = ImGuiTabWidget",
    ):
        assert token in source
