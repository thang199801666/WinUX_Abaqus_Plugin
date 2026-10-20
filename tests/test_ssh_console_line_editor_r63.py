from pathlib import Path

from WinUx.runtime.terminal_buffer import TerminalBuffer


def _commit(buffer, command):
    buffer.type_text(command)
    pending = buffer.begin_submit()
    buffer.command_result(pending, True)


def test_ctrl_r_style_history_search_matches_substrings_and_keeps_query_stable():
    buffer = TerminalBuffer()
    for command in ('git status', 'ls -la', 'sudo git log', 'grep git file'):
        _commit(buffer, command)

    buffer.type_text('git')
    assert buffer.recall_contains(-1) is True
    assert buffer.draft == 'grep git file'
    assert buffer.recall_contains(-1) is True
    assert buffer.draft == 'sudo git log'
    assert buffer.recall_contains(-1) is True
    assert buffer.draft == 'git status'
    assert buffer.recall_contains(-1) is False


def test_editing_after_reverse_history_search_starts_a_fresh_search():
    buffer = TerminalBuffer()
    for command in ('alpha one', 'beta alpha', 'alpha two'):
        _commit(buffer, command)

    buffer.type_text('alpha')
    assert buffer.recall_contains(-1)
    assert buffer.draft == 'alpha two'
    buffer.type_text('!')
    assert buffer.recall_contains(-1) is False


def test_readline_kill_and_yank_round_trip_text_without_affecting_plain_delete():
    buffer = TerminalBuffer()
    buffer.type_text('echo one two')
    assert buffer.kill_word_left() is True
    assert buffer.draft == 'echo one '
    assert buffer.yank() is True
    assert buffer.draft == 'echo one two'

    buffer.cursor = len('echo ')
    assert buffer.kill_to_end() is True
    assert buffer.draft == 'echo '
    assert buffer.yank() is True
    assert buffer.draft == 'echo one two'

    # Plain Delete/Backspace remain ordinary edits and do not overwrite the
    # readline kill buffer used by Ctrl+Y.
    buffer.backspace()
    assert buffer.draft == 'echo one tw'
    assert buffer.yank() is True
    assert buffer.draft.endswith('one two')


def test_console_exposes_readline_chords_in_floating_and_docked_hosts():
    source = (Path(__file__).resolve().parents[1] / 'WinUx' / 'dialogs' / 'console_form.py').read_text(encoding='utf-8')
    for key in ('mvKey_A', 'mvKey_E', 'mvKey_B', 'mvKey_P', 'mvKey_N',
                'mvKey_R', 'mvKey_W', 'mvKey_U', 'mvKey_K', 'mvKey_Y',
                'mvKey_D', 'mvKey_H', 'mvKey_L'):
        assert key in source
    for callback in ('_control_a', '_line_end', '_line_left', '_history_contains',
                     '_kill_word_left', '_kill_to_start', '_kill_to_end', '_yank',
                     '_line_delete', '_line_backspace', '_clear_console'):
        assert callback in source
    assert 'self.view.after(0, self._control_a)' in source
    assert '(dpg.mvKey_R, self._history_contains)' in source


def test_plain_ctrl_a_moves_to_line_start_while_ctrl_shift_a_keeps_select_all():
    source = (Path(__file__).resolve().parents[1] / 'WinUx' / 'dialogs' / 'console_form.py').read_text(encoding='utf-8')
    body = source.split('    def _control_a(self):', 1)[1].split('    def _home(self):', 1)[0]
    assert 'self._shift_down()' in body
    assert 'self._select_all()' in body
    assert 'self._line_home()' in body
