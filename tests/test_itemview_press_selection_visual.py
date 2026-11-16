from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'DearUIQt' / 'modelview' / 'themes.py').read_text(encoding='utf-8')


def test_unselected_pressed_state_uses_selection_fill():
    block_start = SOURCE.index('            else:\n                # Dear ImGui toggles an mvSelectable')
    block = SOURCE[block_start:block_start + 1400]
    assert 'pressed = p.SELECTION_ACTIVE if active else p.SELECTION_INACTIVE' in block
    assert 'pressed = p.BUTTON_ACTIVE if active else p.SELECTION_INACTIVE' not in block
