from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from WinUx.server_model import SSHServerModel


class CompletionModel(SSHServerModel):
    @property
    def connected(self):
        return True

    def __init__(self, items=()):
        super().__init__()
        self.home = PurePosixPath('/home/user')
        self._shell_completion_directory = PurePosixPath('/home/user/work')
        self._items = list(items)

    def list_directory(self, folder):
        return list(self._items)

    def _command_completion_candidates(self, prefix, limit=64):
        return [value for value in ('echo', 'env', 'python', 'pytest')
                if value.startswith(prefix)][:limit]

    def _shell_name_completion_candidates(self, kind, prefix, limit=64):
        source = {
            'user': ('root', 'runner', 'thannguyen'),
            'group': ('root', 'research'),
            'variable': ('HOME', 'HOSTNAME', 'PATH', 'PWD'),
        }.get(kind, ())
        return [value for value in source if value.startswith(prefix)][:limit]


def test_wrappers_preserve_command_position_for_completion():
    model = CompletionModel()
    for draft, expected in (
        ('sudo ec', ['echo']),
        ('sudo -u root ec', ['echo']),
        ('env FOO=1 py', ['python', 'pytest']),
        ('FOO=1 py', ['python', 'pytest']),
        ('command ec', ['echo']),
        ('nohup py', ['python', 'pytest']),
        ('echo ok && ec', ['echo']),
    ):
        result = model.complete_shell_input(draft, len(draft))
        assert result['candidates'] == expected, draft
        assert result['completion_kind'] == 'command', draft


def test_wrapper_arguments_still_complete_files_for_effective_command():
    model = CompletionModel([
        SimpleNamespace(name='Test A.inp', is_dir=False),
        SimpleNamespace(name='TestFolder', is_dir=True),
    ])
    result = model.complete_shell_input('sudo ls Te', len('sudo ls Te'))
    assert result['candidates'] == [r'Test\ A.inp', 'TestFolder/']
    assert result['display_candidates'] == ['Test A.inp', 'TestFolder/']
    assert result['completion_kind'] == 'argument'


def test_sudo_account_and_env_variable_options_use_shell_metadata_completion():
    model = CompletionModel()
    result = model.complete_shell_input('sudo -u th', len('sudo -u th'))
    assert result['candidates'] == ['thannguyen']
    assert result['replacement'] == 'thannguyen '

    result = model.complete_shell_input('sudo -g re', len('sudo -g re'))
    assert result['candidates'] == ['research']

    result = model.complete_shell_input('env -u HO', len('env -u HO'))
    assert result['candidates'] == ['HOME', 'HOSTNAME']
    assert result['common_prefix'] == 'HO'


def test_wrapper_directory_options_never_offer_files():
    model = CompletionModel([
        SimpleNamespace(name='Tests', is_dir=True),
        SimpleNamespace(name='Test.inp', is_dir=False),
    ])
    for draft in ('env -C Te', 'sudo -D Te'):
        result = model.complete_shell_input(draft, len(draft))
        assert result['candidates'] == ['Tests/']
        assert result['replacement'] == 'Tests/'


def test_inline_environment_variable_completion_does_not_add_a_space():
    model = CompletionModel()
    result = model.complete_shell_input('echo $HOM', len('echo $HOM'))
    assert result['candidates'] == ['$HOME']
    assert result['replacement'] == '$HOME'
    assert result['completion_kind'] == 'variable-inline'

    result = model.complete_shell_input('echo ${HOM', len('echo ${HOM'))
    assert result['candidates'] == ['${HOME}']
    assert result['replacement'] == '${HOME}'


def test_double_tab_display_uses_unescaped_remote_names():
    model = CompletionModel([
        SimpleNamespace(name='My File.inp', is_dir=False),
        SimpleNamespace(name='My Folder', is_dir=True),
    ])
    result = model.complete_shell_input('ls My', len('ls My'))
    assert result['candidates'] == [r'My\ File.inp', r'My\ Folder/']
    assert result['display_candidates'] == ['My File.inp', 'My Folder/']

    # Display labels remain human-readable even though CMD-style Tab cycling
    # inserts the escaped candidate value into the command line.
    assert result['display_candidates'][0] != result['candidates'][0]


def test_home_and_pwd_variable_paths_resolve_without_losing_shell_syntax():
    seen = []
    model = CompletionModel([SimpleNamespace(name='Projects', is_dir=True)])

    def listing(folder):
        seen.append(PurePosixPath(folder))
        return [SimpleNamespace(name='Projects', is_dir=True)]

    model.list_directory = listing
    result = model.complete_shell_input('cd $HOME/Pro', len('cd $HOME/Pro'))
    assert seen[-1] == PurePosixPath('/home/user')
    assert result['candidates'] == ['$HOME/Projects/']

    result = model.complete_shell_input('cd ${PWD}/Pro', len('cd ${PWD}/Pro'))
    assert seen[-1] == PurePosixPath('/home/user/work')
    assert result['candidates'] == ['${PWD}/Projects/']
