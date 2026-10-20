"""Helpers for locating canonical UI implementation sources."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WINUX_ROOT = PROJECT_ROOT / "WinUx"
DEAR_UI_QT_ROOT = PROJECT_ROOT / "DearUIQt"


def implementation_path(path):
    """Return the canonical implementation path for legacy-style test inputs.

    Older source-level tests still describe wrapper files relative to
    ``WinUx/ui/framework``.  The implementation now lives physically in the
    root-level ``DearUIQt`` package, so redirect those logical paths here.
    """
    path = Path(path)
    try:
        rel = path.relative_to(WINUX_ROOT)
    except ValueError:
        try:
            rel = path.relative_to(PROJECT_ROOT)
        except ValueError:
            rel = path
    text = rel.as_posix()
    if text.startswith("ui/framework/"):
        return DEAR_UI_QT_ROOT / text[len("ui/framework/"):]
    mapping = {
        "dialogs/base.py": DEAR_UI_QT_ROOT / "dialogs/base.py",
        "dialogs/qt_dialog.py": DEAR_UI_QT_ROOT / "dialogs/qt_dialog.py",
        "dialogs/theme.py": DEAR_UI_QT_ROOT / "dialogs/theme.py",
        "components/dock_widget.py": DEAR_UI_QT_ROOT / "docking/dock_widget.py",
        "components/dock_manager.py": DEAR_UI_QT_ROOT / "docking/dock_manager.py",
        "components/tooltip.py": DEAR_UI_QT_ROOT / "tooltip.py",
        "components/floating_window_resizer.py": DEAR_UI_QT_ROOT / "docking/floating_window_resizer.py",
        # Assets created before the DearUIQt extraction retained old locations.
        "DearUIQt/qt/scroller.py": DEAR_UI_QT_ROOT / "backends/dearpygui_scroller.py",
        "components/explorer_list_view.py": WINUX_ROOT / "ui/components/explorer_list_view.py",
        "components/explorer_layout.py": WINUX_ROOT / "ui/components/explorer_layout.py",
        "components/explorer_hit_testing.py": WINUX_ROOT / "ui/components/explorer_hit_testing.py",
        "WinUx/components/explorer_list_view.py": WINUX_ROOT / "ui/components/explorer_list_view.py",
        "WinUx/components/explorer_layout.py": WINUX_ROOT / "ui/components/explorer_layout.py",
        "WinUx/components/explorer_hit_testing.py": WINUX_ROOT / "ui/components/explorer_hit_testing.py",
    }
    if text in mapping:
        return mapping[text]
    if text.startswith("WinUx/") or text.startswith("DearUIQt/"):
        return PROJECT_ROOT / text
    return WINUX_ROOT / text
