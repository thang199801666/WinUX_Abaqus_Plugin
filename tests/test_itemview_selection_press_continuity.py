from pathlib import Path

THEMES = (Path(__file__).parents[1] / 'DearUIQt' / 'modelview' / 'themes.py').read_text(encoding='utf-8')


def test_unselected_native_toggle_uses_final_selection_fill():
    assert 'selected_fill = p.SELECTION_ACTIVE if active else p.SELECTION_INACTIVE' in THEMES
    assert 'pressed = selected_fill' in THEMES
    block = THEMES.split('else:\n                # Dear ImGui toggles', 1)[1].split('backend.add_theme_color', 1)[0]
    assert 'selected_fill = p.HIGHLIGHT_SOFT' not in block
