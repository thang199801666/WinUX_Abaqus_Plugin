from pathlib import Path

from WinUx.runtime.terminal_buffer import TerminalBuffer


def _commit(buffer, command):
    buffer.type_text(command)
    pending = buffer.begin_submit()
    buffer.command_result(pending, True)


def test_ctrl_word_delete_and_kill_ranges_match_shell_line_editing():
    buffer = TerminalBuffer()
    buffer.type_text('echo one two')
    buffer.delete_word_left()
    assert buffer.draft == 'echo one '
    assert buffer.cursor == len('echo one ')

    buffer.move_cursor(-1, by_word=True)
    assert buffer.cursor == len('echo ')
    buffer.delete_word_right()
    assert buffer.draft == 'echo '

    buffer.type_text('alpha beta')
    buffer.move_cursor(-1, by_word=True)
    buffer.delete_to_start()
    assert buffer.draft == 'beta'
    assert buffer.cursor == 0
    buffer.delete_to_end()
    assert buffer.draft == ''


def test_insert_key_overwrite_mode_only_replaces_typed_characters():
    buffer = TerminalBuffer()
    buffer.type_text('abcdef')
    buffer.cursor = 2
    assert buffer.toggle_overwrite() is True
    buffer.type_text('XY')
    assert buffer.draft == 'abXYef'
    assert buffer.cursor == 4
    buffer.move_end()
    buffer.type_text('!')
    assert buffer.draft == 'abXYef!'
    assert buffer.toggle_overwrite() is False


def test_paste_stays_insertional_even_in_overwrite_mode():
    buffer = TerminalBuffer()
    buffer.type_text('abcd')
    buffer.cursor = 2
    buffer.toggle_overwrite()
    buffer.paste('XY')
    assert buffer.draft == 'abXYcd'
    assert buffer.cursor == 4


def test_f8_style_prefix_history_search_keeps_original_prefix():
    buffer = TerminalBuffer()
    for command in ('git status', 'ls -la', 'git log', 'git diff'):
        _commit(buffer, command)

    buffer.type_text('git ')
    assert buffer.recall_prefix(-1) is True
    assert buffer.draft == 'git diff'
    assert buffer.recall_prefix(-1) is True
    assert buffer.draft == 'git log'
    assert buffer.recall_prefix(-1) is True
    assert buffer.draft == 'git status'
    assert buffer.recall_prefix(-1) is False


def test_ordinary_edit_resets_f8_prefix_search():
    buffer = TerminalBuffer()
    for command in ('alpha one', 'alpha two', 'beta one'):
        _commit(buffer, command)
    buffer.type_text('alpha')
    assert buffer.recall_prefix(-1)
    assert buffer.draft == 'alpha two'
    buffer.type_text('!')
    # New text establishes a fresh prefix; old alpha-cycle state must be gone.
    assert buffer.recall_prefix(-1) is False


def test_console_registers_cmd_style_editing_keys_for_both_hosts():
    source = (Path(__file__).resolve().parents[1] / 'WinUx' / 'dialogs' / 'console_form.py').read_text(encoding='utf-8')
    for token in (
        'mvKey_F8', 'mvKey_Insert', 'mvKey_W', 'mvKey_U', 'mvKey_K',
        '_delete_word_left', '_delete_word_right', '_delete_to_start',
        '_delete_to_end', '_history_prefix', '_toggle_overwrite',
        '_dock_ctrl_edit_callback', '_run_key_with_modifiers',
    ):
        assert token in source
    assert 'if self._ctrl_down():\n            self.buffer.delete_word_left()' in source
    assert 'if self._ctrl_down():\n            self.buffer.delete_word_right()' in source


def test_renderer_exposes_overwrite_mode_with_block_caret():
    source = (Path(__file__).resolve().parents[1] / 'WinUx' / 'ui' / 'components' / 'console_renderer.py').read_text(encoding='utf-8')
    assert 'overwrite_mode' in source
    assert 'caret_height = max(2, int(view._line_height) - 4) if overwrite else 2' in source
