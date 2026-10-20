from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py"


def test_plot_digitizer_ribbon_uses_normal_density_and_wider_large_icon_tiles():
    source = FORM.read_text(encoding="utf-8")
    assert 'density="compact"' in source
    assert 'self.ribbon.LARGE_ICON_SIZE = 32' in source
    assert 'width=64, image=self._icon("open_image")' in source
    assert 'width=64, image=self._icon("undo")' in source
    assert 'width=64, image=self._icon("zoom_in")' in source


def test_plot_digitizer_icon_actions_draw_icons_inside_the_single_qpushbutton_frame():
    source = FORM.read_text(encoding="utf-8")
    block = source.split('def _icon_action(', 1)[1].split('def _icon_only_action(', 1)[0]
    assert 'host = dpg.add_child_window(' in block
    assert 'dpg.bind_item_theme(host, transparent_header_cell_theme())' in block
    assert 'display_label = "   " + str(label)' in block
    assert 'overlay = dpg.add_drawlist(' in block
    assert 'image = dpg.draw_image(' in block
    assert 'callback=lambda *_args, tag=button: self._click_icon_action(tag)' in block
    assert 'dpg.add_image_button(' not in block


def test_plot_digitizer_dense_icon_only_buttons_keep_original_22px_geometry_and_fit_icon_inside():
    source = FORM.read_text(encoding="utf-8")
    assert 'def _icon_only_action(self, icon_name, callback, *, parent, tooltip="", button_size=22):' in source
    assert 'tooltip="Add dataset", button_size=22' in source
    assert 'tooltip="Delete active dataset", button_size=22' in source
    assert 'tooltip="Pick {} anchor".format(label), button_size=22' in source
    assert 'COMPACT_ICON_RENDER_SIZE = 18' in source
    assert 'render_size = max(16, min(int(button_size) - 4, self.COMPACT_ICON_RENDER_SIZE))' in source
    assert 'toolbar_fitted_icon_theme()' in source
