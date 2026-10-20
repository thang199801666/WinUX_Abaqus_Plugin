"""Regression: editable combo uses a clipped full-width native popup owner."""
from pathlib import Path


def _source():
    return (Path(__file__).resolve().parents[1] / 'DearUIQt/widgets/combo_box.py').read_text(encoding='utf-8')


def test_editable_combo_has_independent_editor_and_arrow_hit_areas():
    source = _source()
    constructor = source.split('class ImGuiComboBox:', 1)[1].split('def _native_value_for', 1)[0]
    assert 'self._row = dpg.add_group(' in constructor
    assert 'self.input = dpg.add_input_text(' in constructor
    assert 'width=-editor_right_reserve' in constructor
    assert 'self._arrow_clip = dpg.add_child_window(' in constructor
    assert 'width=self._native_arrow_width' in constructor
    combo = constructor.split('self.button = dpg.add_combo(', 1)[1].split('\n        )', 1)[0]
    assert 'parent=self._arrow_clip' in combo
    assert 'no_preview=False' in combo
    assert 'width=initial_combo_width' in combo
    assert 'pos=(-initial_hidden_preview, 0)' in combo


def test_native_combo_bbox_tracks_full_control_width_for_popup():
    source = _source()
    sync = source.split('def _sync_geometry', 1)[1].split('def _install_handlers', 1)[0]
    assert 'dpg.get_item_rect_size(self.shell)[0]' in sync
    assert 'shell_width - 2 * METRICS.border_size' in sync
    assert 'combo_width - self._native_arrow_width' in sync
    assert 'self.button, width=combo_width' in sync
    assert 'pos=(-hidden_preview, 0)' in sync


def test_combo_keeps_native_selection_and_editable_text():
    source = _source()
    assert 'callback=self._native_selected' in source
    assert 'callback=self._input_changed' in source
    assert 'self.set_current_text(value, emit=True)' in source
    assert 'self._popup = None' in source
    assert 'dpg.add_window(' not in source.split('class ImGuiComboBox:', 1)[1].split('class QComboBox(QWidget):', 1)[0]
