from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "job_schedule_form.py"
STYLE = ROOT / "DearUIQt" / "gui" / "style.py"


def test_job_schedule_uses_qtablewidget_native_header_surface():
    source = FORM.read_text(encoding="utf-8")
    assert 'QTableWidget(' in source
    assert 'setHorizontalHeaderLabels' in source
    assert 'transparent_header_cell_theme' not in source


def test_transparent_header_cell_theme_remains_available_for_legacy_surfaces():
    source = STYLE.read_text(encoding="utf-8")
    assert 'def transparent_header_cell_theme(backend):' in source
    assert 'backend.add_theme_color(backend.mvThemeCol_ChildBg, (0, 0, 0, 0))' in source
    assert 'backend.add_theme_color(backend.mvThemeCol_Border, (0, 0, 0, 0))' in source
    assert 'backend.add_theme_style(backend.mvStyleVar_WindowPadding, 0, 0)' in source
    assert 'backend.add_theme_style(backend.mvStyleVar_ChildBorderSize, 0)' in source
    assert '"transparent_header_cell_theme"' in source
