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


def test_first_tab_expands_exactly_to_first_divergence():
    model = CompletionModel([
        SimpleNamespace(name='Test-17-0285.com', is_dir=False),
        SimpleNamespace(name='Test-17-0285.inp', is_dir=False),
        SimpleNamespace(name='Test-17-0285.log', is_dir=False),
        SimpleNamespace(name='Test-17-0285.que', is_dir=False),
    ])
    draft = 'ls T'
    result = model.complete_shell_input(draft, len(draft))
    assert result['common_prefix'] == 'Test-17-0285.'
    assert result['candidates'] == [
        'Test-17-0285.com', 'Test-17-0285.inp',
        'Test-17-0285.log', 'Test-17-0285.que']


def test_typing_after_divergence_recomputes_the_next_safe_pattern():
    model = CompletionModel([
        SimpleNamespace(name='Test-17-0285.com', is_dir=False),
        SimpleNamespace(name='Test-17-0285.config', is_dir=False),
        SimpleNamespace(name='Test-17-0285.copy', is_dir=False),
        SimpleNamespace(name='Test-17-0285.inp', is_dir=False),
    ])
    draft = 'ls Test-17-0285.c'
    result = model.complete_shell_input(draft, len(draft))
    assert result['common_prefix'] == 'Test-17-0285.co'
    assert result['candidates'] == [
        'Test-17-0285.com', 'Test-17-0285.config', 'Test-17-0285.copy']


def test_cd_pattern_still_filters_regular_files_before_divergence():
    model = CompletionModel([
        SimpleNamespace(name='Test-A', is_dir=True),
        SimpleNamespace(name='Test-B', is_dir=True),
        SimpleNamespace(name='Test-A.inp', is_dir=False),
    ])
    draft = 'cd T'
    result = model.complete_shell_input(draft, len(draft))
    assert result['candidates'] == ['Test-A/', 'Test-B/']
    assert result['common_prefix'] == 'Test-'


def test_console_cycles_concrete_matches_after_safe_prefix_and_supports_shift_tab():
    source = (Path(__file__).resolve().parents[1] / 'WinUx' / 'dialogs' / 'console_form.py').read_text(encoding='utf-8')
    assert 'self._cycle_completion_state(state, direction)' in source
    assert 'step = -1 if int(direction or 1) < 0 else 1' in source
    assert 'index = len(candidates) - 1 if step < 0 else 0' in source
    assert 'index = (index + step) % len(candidates)' in source
    assert '"candidate_index": -1' in source


def test_extra_tabs_during_async_lookup_are_replayed_instead_of_lost():
    source = (Path(__file__).resolve().parents[1] / 'WinUx' / 'dialogs' / 'console_form.py').read_text(encoding='utf-8')
    assert 'self._completion_queued_directions.append(direction)' in source
    assert 'queued_directions = list(self._completion_queued_directions)' in source
    assert 'for queued_direction in queued_directions:' in source
    assert 'self._cycle_completion_state(state, queued_direction)' in source
