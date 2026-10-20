"""App cwd sync is silent now: the cd command echo is suppressed at the send site."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

def test_no_hidden_transcript_rewrite_queue_remains():
    src = read('WinUx/server_model.py')
    assert '_remove_hidden_command_echo' not in src
    assert '_hidden_shell_commands' not in src

def test_server_browsing_syncs_console_shell_without_transcript_noise():
    # Browsing keeps the SSH console cwd aligned with the Server Files panel,
    # but the app-generated cd command echo is suppressed at the send site
    # (show_echo=False) instead of ever landing in the live PTY transcript.
    assert 'self.server.set_shell_directory(path)' in read('WinUx/controllers/navigation.py')
    assert 'self.server.set_shell_directory(folder)' in read('WinUx/controllers/connection.py')
    src = read('WinUx/server_model.py')
    assert 'command, show_echo=False, replace_prompt=True)' in src
