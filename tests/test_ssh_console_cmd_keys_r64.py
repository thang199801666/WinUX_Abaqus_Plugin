from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from WinUx.runtime.terminal_buffer import TerminalBuffer
from WinUx.server_model import SSHServerModel


def _commit(buffer, command):
    buffer.type_text(command)
    pending = buffer.begin_submit()
    buffer.command_result(pending, True)


def test_f1_copies_previous_command_one_column_at_a_time():
    buffer = TerminalBuffer()
    _commit(buffer, 'echo alpha')
    assert buffer.copy_template_char() is True
    assert buffer.draft == 'e'
    assert buffer.copy_template_char() is True
    assert buffer.draft == 'ec'
    buffer.type_text('XX')
    assert buffer.cursor == 4
    assert buffer.copy_template_char() is True
    assert buffer.draft == 'ecXX '


def test_f3_copies_template_remainder_from_current_column_and_replaces_suffix():
    buffer = TerminalBuffer()
    _commit(buffer, 'cd Test-17-0285')
    buffer.type_text('cd TeWRONG')
    buffer.cursor = len('cd Te')
    assert buffer.copy_template_remainder() is True
    assert buffer.draft == 'cd Test-17-0285'
    assert buffer.cursor == len(buffer.draft)


def test_f5_restores_complete_previous_command_template():
    buffer = TerminalBuffer()
    _commit(buffer, 'abaqus job=beam interactive')
    buffer.type_text('something else')
    assert buffer.copy_template() is True
    assert buffer.draft == 'abaqus job=beam interactive'
    assert buffer.cursor == len(buffer.draft)


class CompletionModel(SSHServerModel):
    @property
    def connected(self):
        return True

    def __init__(self):
        super().__init__()
        self.home = PurePosixPath('/home/user')
        self._shell_completion_directory = PurePosixPath('/home/user/work')

    def list_directory(self, folder):
        return [
            SimpleNamespace(name='result.log', is_dir=False),
            SimpleNamespace(name='results', is_dir=True),
            SimpleNamespace(name='error.log', is_dir=False),
        ]


def test_redirection_target_is_a_separate_completion_token_without_resetting_command():
    model = CompletionModel()
    for draft in ('grep foo>res', 'grep foo >> res', 'python x.py 2>err'):
        result = model.complete_shell_input(draft, len(draft))
        if draft.endswith('res'):
            assert result['candidates'] == ['result.log', 'results/']
            assert result['common_prefix'] == 'result'
        else:
            assert result['candidates'] == ['error.log']
            assert result['replacement'] == 'error.log '
        assert result['completion_kind'] == 'argument'


def test_mid_token_redirection_completion_does_not_consume_operator_or_suffix():
    model = CompletionModel()
    text = 'cat>res tail'
    cursor = text.index(' tail')
    ctx = model._completion_word_context(text, cursor)
    assert text[ctx['start']:cursor] == 'res'
    assert ctx['start'] == text.index('res')
    assert ctx['end'] == cursor


def test_console_wires_cmd_template_keys_for_floating_and_docked_hosts():
    source = (Path(__file__).resolve().parents[1] / 'WinUx' / 'dialogs' / 'console_form.py').read_text(encoding='utf-8')
    assert 'mvKey_F1' in source
    assert 'mvKey_F3' in source
    assert 'mvKey_F5' in source
    assert '_template_char' in source
    assert '_template_remainder' in source
    assert '_template_full' in source
    assert 'user_data=self._template_char' in source
    assert 'user_data=self._template_full' in source
    assert 'self.view.after(0, self._template_remainder)' in source
