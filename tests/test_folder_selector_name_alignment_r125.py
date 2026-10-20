from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / 'WinUx' / 'dialogs' / 'folder_browser_style.py').read_text(encoding='utf-8')
FORM = (ROOT / 'WinUx' / 'dialogs' / 'local_folder_form.py').read_text(encoding='utf-8')


def test_name_selectable_is_vertically_centered_like_detail_cells():
    block = STYLE.split('def browser_name_item_theme', 1)[1].split('def browser_selected_text_theme', 1)[0]
    assert 'ThemeStyle.SELECTABLE_TEXT_ALIGN: (0.0, 0.5)' in block
    assert 'ThemeStyle.FRAME_PADDING: (5, 2)' in block


def test_selected_name_theme_keeps_same_vertical_alignment():
    block = STYLE.split('def browser_selected_item_theme', 1)[1].split('def browser_name_item_theme', 1)[0]
    assert 'ThemeStyle.SELECTABLE_TEXT_ALIGN: (0.0, 0.5)' in block
    assert 'ThemeStyle.FRAME_PADDING: (5, 2)' in block


def test_folder_icon_is_exactly_centered_with_name_text():
    assert 'icon_y = max(0, (METRICS.row_height - 16) // 2)' in FORM
    assert '// 2 + 1' not in FORM
    assert '(1, icon_y)' in FORM
    assert '(17, icon_y + 16)' in FORM


def test_folder_list_binds_centered_name_theme_for_all_dirty_states():
    block = FORM.split('def _sync_selection_visuals', 1)[1].split('def _sorted', 1)[0]
    assert 'browser_name_item_theme(' in block
    assert 'state = (chosen, disabled, current, active)' in block
    assert 'self.backend.bind_item_theme(native, theme)' in block
