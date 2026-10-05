from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

def test_server_model_no_transcript_rewrite_or_hidden_command_queue():
    src = read('WinUx/server_model.py')
    assert '_remove_hidden_command_echo' not in src
    assert '_hidden_shell_commands' not in src
    assert 'def send_shell_command(self, command):' in src

def test_navigation_does_not_inject_cd_into_console_shell():
    nav = read('WinUx/controllers/navigation.py')
    conn = read('WinUx/controllers/connection.py')
    assert 'self.server.set_shell_directory(path)' not in nav
    assert 'self.server.set_shell_directory(folder)' not in conn

def test_console_right_click_returns_to_pre_noise_qmenu_path():
    src = read('WinUx/dialogs/console_form.py')
    block = src[src.index('    def _right_click('):src.index('    def _hide_context_menu(')]
    assert 'menu.popup((mx, my), context=self)' in block
    assert 'native_right_click' not in src
