from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py"
ICON_DIR = ROOT / "WinUx" / "Resources" / "plotdigitizer_icons"


def test_generated_panel_icons_are_wired_to_corresponding_plot_digitizer_actions():
    source = FORM.read_text(encoding="utf-8")
    expected = {
        'Add Point (A)': 'add_point',
        'Edit Points (S)': 'edit_points',
        'Sample Color': 'sample_color',
        'Find Colors': 'find_colors',
        'Extract Points': 'extract_points',
    }
    for label, icon in expected.items():
        assert f'"{label}", "{icon}"' in source
        assert (ICON_DIR / f"{icon}.png").is_file()


def test_icon_action_keeps_qpushbutton_canonical_and_draws_icon_inside_frame():
    source = FORM.read_text(encoding="utf-8")
    block = source.split('def _icon_action(', 1)[1].split('def _icon_only_action(', 1)[0]
    assert 'ResourceTextures.get(self._icon(name), pixel_size=pixel_size)' in source
    assert 'DECORATIVE_ICON_SIZE = 16' in source
    assert 'host = dpg.add_child_window(' in block
    assert 'display_label = "   " + str(label)' in block
    assert 'overlay = dpg.add_drawlist(' in block
    assert 'image = dpg.draw_image(' in block
    assert 'self._icon_action_draws[button] = image' in block
    assert 'wrapper.click()' in block
    assert 'def set_control_enabled(self, item, enabled):' in source


def test_edit_points_icon_dispatches_the_existing_checkable_edit_mode_contract():
    source = FORM.read_text(encoding="utf-8")
    assert 'checkable=True, toggled=self._edit_mode_toggled' in source
    assert 'checkable=True, toggled=self._edit_mode_toggled' in source
    assert 'button = self._toggle_action(' in source
