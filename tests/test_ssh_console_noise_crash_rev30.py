from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

def test_server_model_no_transcript_rewrite_or_hidden_command_queue():
    src = read('WinUx/server_model.py')
    assert '_remove_hidden_command_echo' not in src
    assert '_hidden_shell_commands' not in src
    assert 'def send_shell_command(self, command' in src

def test_navigation_syncs_console_shell_without_command_echo():
    # Rev30 wanted no cd injection at all; the current design intentionally
    # keeps the SSH console cwd aligned with Server Files (see navigation.py /
    # connection.py), while server_model suppresses the app-generated cd echo
    # at the send site so the transcript stays noise-free.
    nav = read('WinUx/controllers/navigation.py')
    conn = read('WinUx/controllers/connection.py')
    assert 'self.server.set_shell_directory(path)' in nav
    assert 'self.server.set_shell_directory(folder)' in conn
    assert 'command, show_echo=False, replace_prompt=True)' in read('WinUx/server_model.py')
    assert '_remove_hidden_command_echo' not in read('WinUx/server_model.py')

def test_console_right_click_opens_modeless_qmenu_popup():
    src = read('WinUx/dialogs/console_form.py')
    start = src.index('    def native_right_click(self, x=None, y=None):')
    end = src.index('    def _terminal_rect_contains', start)
    block = src[start:end]
    assert 'menu.popup(position, context=self)' in block
    assert 'TrackPopupMenuEx' not in src
