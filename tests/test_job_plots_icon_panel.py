"""Regression contracts for the compact Job Viewer / Plots panel."""
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from WinUx.ui.components.job_plots import JobPlotsWindow


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "WinUx/ui/components/job_plots.py").read_text(encoding="utf-8")


def test_plots_has_all_four_shipped_alpha_icons():
    directory = ROOT / "WinUx/Resources/job_plots_icons"
    for icon in ("fit", "reference", "select_all", "select_none"):
        with Image.open(directory / (icon + ".png")) as png:
            assert png.mode == "RGBA"
            assert png.size == (48, 48)
            assert png.getchannel("A").getextrema() == (0, 255)


def test_plot_actions_are_qt_icon_buttons_with_explanatory_tooltips():
    for action in ("fit", "reference", "select_all", "select_none"):
        assert '"' + action + '"' in SOURCE
    assert 'button = QToolButton(' in SOURCE
    assert 'button.setTheme(plot_panel_icon_theme())' in SOURCE
    assert 'QToolTip(button, delay=0.55' in SOURCE
    assert 'self.fit_button = QPushButton(' not in SOURCE
    assert 'self.reference_button = QPushButton(' not in SOURCE
    assert 'self.all_button = QPushButton(' not in SOURCE
    assert 'self.none_button = QPushButton(' not in SOURCE


def test_live_selected_count_updates_without_rebuilding_catalog():
    class Label:
        def __init__(self):
            self.value = ''
        def exists(self):
            return True
        def text(self):
            return self.value
        def setText(self, text):
            self.value = text

    label = Label()
    panel = SimpleNamespace(
        catalog={'a': {}, 'b': {}, 'c': {}}, selected_ids={'a'},
        _count_label=label, _client_layout_signature=None)
    JobPlotsWindow._update_history_count(panel)
    assert label.value == '1 / 3'
    panel.selected_ids.clear()
    JobPlotsWindow._update_history_count(panel)
    assert label.value == '0 / 3'


def test_select_all_none_keep_callbacks_and_counter_synchronized():
    class Checkbox:
        _deleted = False
        def __init__(self): self.value = None
        def setChecked(self, value): self.value = value

    checkboxes = {'a': Checkbox(), 'b': Checkbox()}
    messages = []
    panel = SimpleNamespace(
        catalog={'a': {}, 'b': {}}, selected_ids=set(),
        _checkboxes=checkboxes, _series_tags={}, _series_points={},
        _update_history_count=lambda: messages.append('count'),
        _notify_selection_changed=lambda: messages.append('notify'),
    )
    JobPlotsWindow._set_all(panel, True)
    assert panel.selected_ids == {'a', 'b'}
    assert all(checkbox.value for checkbox in checkboxes.values())
    JobPlotsWindow._set_all(panel, False)
    assert panel.selected_ids == set()
    assert all(checkbox.value is False for checkbox in checkboxes.values())
    assert messages == ['count', 'notify', 'count', 'notify']


def test_layout_avoids_configuring_image_button_dimensions():
    # Renderer image sizes are icon-content bounds, not the outer Qt hitbox.
    # Regression: forcing 52/140px widths turns icon buttons into huge hit areas.
    assert 'self._safe_configure(self.fit_button, pos=(fit_x, fit_y))' in SOURCE
    assert 'self._safe_configure(self.reference_button, pos=(reference_x, fit_y))' in SOURCE
    assert 'self._safe_configure(self.all_button, pos=(inner_pad, button_row_y))' in SOURCE
    assert 'pos=(inner_pad + icon_w + self.ICON_GAP, button_row_y)' in SOURCE
