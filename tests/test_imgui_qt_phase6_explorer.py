from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "WinUx" / "components"


def test_explorer_header_exposes_qheaderview_contract():
    source = (COMPONENTS / "explorer_header_view.py").read_text(encoding="utf-8")
    for token in (
        "class ExplorerHeaderView",
        'Interactive = "interactive"',
        'Fixed = "fixed"',
        'Stretch = "stretch"',
        "def setSectionsMovable",
        "def setSectionsClickable",
        "def setSectionResizeMode",
        "def resizeSection",
        "def sectionSize",
    ):
        assert token in source


def test_explorer_listview_exposes_qabstractitemview_visual_properties():
    source = (COMPONENTS / "explorer_list_view.py").read_text(encoding="utf-8")
    for token in (
        "def horizontalHeader",
        "def setAlternatingRowColors",
        "def setShowGrid",
        "def setHeaderVisible",
        "def selectionMode",
        "def setSelectionMode",
        "def currentIndex",
        "def setCurrentIndex",
    ):
        assert token in source


def test_file_panels_use_shared_qt_itemview_metrics_not_winscp_theme():
    source = (COMPONENTS / "file_panel.py").read_text(encoding="utf-8")
    assert 'theme="Explorer"' in source
    assert 'theme="WinSCP"' not in source
    assert "row_height=23" in source
    assert "header_height=26" in source
    assert 'auto_fit_column_key="name"' in source
    assert "header.setSectionResizeMode(0, header.Stretch)" in source


def test_explorer_active_selection_matches_qt_focus_roles():
    theme = (COMPONENTS / "explorer_themes.py").read_text(encoding="utf-8")
    render = (COMPONENTS / "explorer_rendering.py").read_text(encoding="utf-8")
    assert '"selected_fill": QtFusionPalette.HIGHLIGHT' in theme
    assert '"selected_text": QtFusionPalette.HIGHLIGHT_TEXT' in theme
    assert '"inactive_selected_fill": QtFusionPalette.SELECTION_INACTIVE' in theme
    assert '"row_rounding": 0.0' in theme
    assert "1.0 if current else 0.0" in render
    assert "self._alternating_row_colors and index % 2" in render


def test_explorer_rows_use_full_width_flat_selection_geometry():
    render = (COMPONENTS / "explorer_rendering.py").read_text(encoding="utf-8")
    layout = (COMPONENTS / "explorer_layout.py").read_text(encoding="utf-8")
    assert "pmin=(0.5, y0 + 0.5)" in layout
    assert "visible_width - 0.5" in layout
    assert "pmin=(0.5, 0.5)" in render
