from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py"
ICON_DIR = ROOT / "WinUx" / "Resources" / "plotdigitizer_icons"


def test_plot_digitizer_uses_dedicated_raster_icon_pack_for_ribbon_buttons():
    source = FORM.read_text(encoding="utf-8")
    assert 'ICON_ROOT = "plotdigitizer_icons"' in source
    assert 'def _icon(cls, name: str) -> str:' in source
    for name in (
        'open_image', 'load_project', 'save_project', 'export_csv',
        'undo', 'redo', 'fit_view', 'one_to_one', 'zoom_out', 'zoom_in', 'plot_area',
    ):
        assert f'image=self._icon("{name}")' in source


def test_plot_digitizer_generated_png_icons_exist_without_svg_dependencies():
    assert ICON_DIR.is_dir()
    expected = {
        'open_image.png', 'load_project.png', 'save_project.png', 'export_csv.png',
        'undo.png', 'redo.png', 'fit_view.png', 'one_to_one.png', 'zoom_out.png', 'zoom_in.png',
        'plot_area.png', 'add_point.png', 'edit_points.png', 'sample_color.png',
        'find_colors.png', 'extract_points.png', 'add_item.png', 'delete_item.png',
        'delete_points.png', 'clear_points.png', 'reduce_samples.png', 'calibrate_axes.png',
        'apply_changes.png', 'reset.png', 'detect_area.png', 'pick_anchor.png', 'source_sheet.png',
    }
    found = {path.name for path in ICON_DIR.glob('*.png')}
    assert expected.issubset(found)
    assert not list(ICON_DIR.glob('*.svg'))


def test_plot_digitizer_icon_pack_keeps_expected_raster_sizes():
    from PIL import Image

    for path in ICON_DIR.glob('*.png'):
        with Image.open(path) as img:
            if path.name == 'source_sheet.png':
                assert img.size[0] >= 1000 and img.size[1] >= 1000
            else:
                assert img.size in ((64, 64), (128, 128))
