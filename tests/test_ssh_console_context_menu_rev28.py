from pathlib import Path


def test_console_context_menu_does_not_use_imgui_popup_stack():
    source = Path('WinUx/dialogs/console_form.py').read_text(encoding='utf-8')
    create_start = source.index('    def _create_context_menu(')
    create_end = source.index('    def _right_click(', create_start)
    create_block = source[create_start:create_end]
    assert 'dpg.window(' in create_block
    assert 'popup=True' not in create_block
    assert 'QMenu(' not in create_block


def test_right_click_remains_deferred_and_safe_window_is_shown():
    source = Path('WinUx/dialogs/console_form.py').read_text(encoding='utf-8')
    start = source.index('    def _right_click(')
    end = source.index('    def _menu_action(', start)
    block = source[start:end]
    right_click = block[:block.index('    def _show_context_menu_deferred(')]
    deferred = block[block.index('    def _show_context_menu_deferred('):]
    assert 'self.view.after(0, lambda: self._show_context_menu_deferred(mx, my))' in right_click
    assert '.popup(' not in block
    assert 'dpg.configure_item(self._context_menu, show=True)' in deferred
    assert '_context_menu_pending' in block
