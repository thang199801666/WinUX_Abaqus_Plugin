from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py"
TOOLBAR = ROOT / "WinUx" / "ui" / "components" / "toolbar.py"
STYLE = ROOT / "DearUIQt" / "qt" / "style.py"


def test_plot_digitizer_restores_original_button_geometry_and_fits_icon_with_small_padding():
    form = FORM.read_text(encoding="utf-8")
    toolbar = TOOLBAR.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert 'button_size=22' in form
    assert 'toolbar_fitted_icon_theme()' in form
    assert 'def toolbar_fitted_icon_theme():' in toolbar
    assert 'frame_padding=(1, 1)' in toolbar
    assert 'def tool_button_theme(backend, *, disabled=False, frame_padding=(4, 3)):' in style
    assert 'backend.add_theme_style(backend.mvStyleVar_FramePadding, pad_x, pad_y)' in style


def test_plot_digitizer_ribbon_keeps_original_tile_widths_but_increases_icon_area_only():
    form = FORM.read_text(encoding="utf-8")
    assert 'density="compact"' in form
    assert 'self.ribbon.LARGE_ICON_SIZE = 32' in form
    assert 'width=64, image=self._icon("open_image")' in form
    assert 'width=64, image=self._icon("zoom_in")' in form
