"""Superseded by rev30: app-generated cwd sync is removed instead of rewriting PTY history."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

def test_no_hidden_transcript_rewrite_queue_remains():
    src = read('WinUx/server_model.py')
    assert '_remove_hidden_command_echo' not in src
    assert '_hidden_shell_commands' not in src

def test_server_browsing_no_longer_injects_automatic_cd_commands():
    assert 'self.server.set_shell_directory(path)' not in read('WinUx/controllers/navigation.py')
    assert 'self.server.set_shell_directory(folder)' not in read('WinUx/controllers/connection.py')
