from pathlib import Path


def test_remote_check_odb_does_not_reference_undefined_singular_launcher():
    source = Path('WinUx/services/odb/remote.py').read_text(encoding='utf-8')
    start = source.index('    def check_odb(self, path, abaqus_commands=None):')
    end = source.index('    def _run_odb_extract_mode', start)
    block = source[start:end]
    assert 'str(abaqus_command or "").strip()' not in block
    assert 'self._resolve_abaqus_for_odb_on(' in block
    assert 'abaqus_commands)' in block
