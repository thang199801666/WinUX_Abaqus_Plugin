from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py"
ICON_DIR = ROOT / "WinUx" / "Resources" / "plotdigitizer_icons"


def test_remaining_semantic_actions_use_dedicated_icons():
    source = FORM.read_text(encoding="utf-8")
    expected = {
        'Delete': 'delete_points',
        'Clear All': 'clear_points',
        'Reduce Samples': 'reduce_samples',
        'Delete Point (D)': 'delete_points',
        'Align Axes - Pick 4 Points': 'calibrate_axes',
        'Apply Calibration': 'apply_changes',
        'Calibrate Area': 'plot_area',
        'Reset Axes': 'reset',
        'Apply Point': 'apply_changes',
        'Detect Area': 'detect_area',
        'Reset Area': 'reset',
    }
    for label, icon in expected.items():
        assert f'"{label}", "{icon}"' in source
        assert (ICON_DIR / f"{icon}.png").is_file()


def test_dense_dataset_and_anchor_actions_use_icon_only_buttons():
    source = FORM.read_text(encoding="utf-8")
    assert 'def _icon_only_action(' in source
    assert '"add_item", self._add_dataset' in source
    assert '"delete_item", self._delete_dataset' in source
    assert '"pick_anchor", lambda: self._begin_pick(key)' in source
    assert 'dpg.add_image_button(' in source
    assert 'button_size=22' in source
    assert 'self._remember_focusable(button)' in source


def test_new_generated_icons_are_transparent_pngs():
    from PIL import Image

    names = (
        'add_item', 'delete_item', 'delete_points', 'clear_points', 'reduce_samples',
        'calibrate_axes', 'apply_changes', 'reset', 'detect_area', 'pick_anchor',
    )
    for name in names:
        path = ICON_DIR / f"{name}.png"
        assert path.is_file()
        with Image.open(path).convert('RGBA') as img:
            assert img.size in ((64, 64), (128, 128))
            assert img.getpixel((0, 0))[3] == 0
            assert img.getbbox() is not None


def test_previous_next_navigation_uses_compact_raster_icon_buttons():
    source = FORM.read_text(encoding="utf-8")
    assert '"previous_point", lambda: self._navigate_point(-1)' in source
    assert '"next_point", lambda: self._navigate_point(1)' in source
    assert (ICON_DIR / "previous_point.png").is_file()
    assert (ICON_DIR / "next_point.png").is_file()
