"""Source-level regression checks for editable QComboBox full-width native popup."""
from pathlib import Path


def _source():
    return (Path(__file__).resolve().parents[1] / "DearUIQt" / "widgets" /
            "combo_box.py").read_text(encoding="utf-8")


def test_native_popup_owner_is_full_width_and_precedes_editor():
    constructor = _source().split("class ImGuiComboBox", 1)[1].split(
        "# Compatibility names retained", 1)[0]
    assert 'parent=self.shell,' in constructor
    assert 'pos=(0, 0)' in constructor
    assert 'width=-1,' in constructor
    assert 'no_preview=False' in constructor
    assert constructor.index('self.button = dpg.add_combo(') < constructor.index(
        'self.input = dpg.add_input_text(')
    assert 'pos=(1, 1)' in constructor
    assert 'width=-editor_right_reserve' in constructor


def test_popup_does_not_use_detached_window_or_unsupported_arrow_glyph():
    source = _source()
    assert 'self._popup = dpg.add_window(' not in source
    assert 'label="▾"' not in source
    assert 'callback=self._native_selected' in source
    geometry = source.split('def _sync_geometry(self, *_args):', 1)[1].split(
        'def _install_handlers(self)', 1)[0]
    assert 'dpg.configure_item(self.button, pos=(0, 0), width=-1)' in geometry
