from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from WinUx.server_model import SSHServerModel


def test_completion_word_context_understands_paths_quotes_and_command_position():
    ctx = SSHServerModel._completion_word_context("ec", 2)
    assert ctx["command_position"] is True
    assert ctx["value"] == "ec"

    text = r"cd My\ Folder/Do"
    ctx = SSHServerModel._completion_word_context(text, len(text))
    assert ctx["command_position"] is False
    assert ctx["value"] == "My Folder/Do"
    assert ctx["start"] == 3

    text = 'cat "My Folder/re'
    ctx = SSHServerModel._completion_word_context(text, len(text))
    assert ctx["value"] == "My Folder/re"
    assert ctx["quote"] == '"'


def test_path_completion_escapes_spaces_and_marks_directories():
    model = SSHServerModel()
    model.home = PurePosixPath("/home/user")
    model._shell_completion_directory = PurePosixPath("/home/user/work")
    model.list_directory = lambda folder: [
        SimpleNamespace(name="My Folder", is_dir=True),
        SimpleNamespace(name="My File.inp", is_dir=False),
        SimpleNamespace(name="Other", is_dir=True),
        SimpleNamespace(name=".hidden", is_dir=False),
    ]
    assert model._path_completion_candidates("My") == [
        r"My\ Folder/", r"My\ File.inp"]
    assert model._path_completion_candidates(".h") == [".hidden"]


def test_simple_cd_updates_completion_cwd_without_changing_strict_cache():
    model = SSHServerModel()
    model.home = PurePosixPath("/home/user")
    model._shell_completion_directory = PurePosixPath("/home/user/work")
    model._shell_directory = PurePosixPath("/home/user/work")
    model.note_shell_command("cd ../jobs")
    assert model._shell_completion_directory == PurePosixPath("/home/user/jobs")
    # Navigation cache remains a separate concern until explicitly invalidated.
    assert model._shell_directory == PurePosixPath("/home/user/work")
    model.invalidate_shell_directory()
    assert model._shell_directory is None
    assert model._shell_completion_directory == PurePosixPath("/home/user/jobs")


def test_compound_cwd_change_is_not_guessed():
    model = SSHServerModel()
    model.home = PurePosixPath("/home/user")
    model._shell_completion_directory = PurePosixPath("/home/user/work")
    model.note_shell_command("cd ../jobs && pwd")
    assert model._shell_completion_directory is None


def test_console_tab_is_remote_completion_not_literal_tab():
    source = (Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
    tab_body = source.split("    def _tab(self):", 1)[1].split("    def _paste(self):", 1)[0]
    assert 'self.buffer.type_text("\\t")' not in tab_body
    assert "completion_callback" in tab_body
    assert "_completion_result" in tab_body
    # Shift+Tab cycles backwards; the shift modifier is resolved via QKeyboard
    # (possibly through a queued modifier snapshot) instead of raw mvKey codes.
    assert "_shift_down()" in tab_body


def test_completion_is_wired_through_controller_view_and_floating_dock():
    root = Path(__file__).resolve().parents[1]
    controller = (root / "WinUx" / "controller.py").read_text(encoding="utf-8")
    callbacks = (root / "WinUx" / "controllers" / "callbacks.py").read_text(encoding="utf-8")
    view = (root / "WinUx" / "view.py").read_text(encoding="utf-8")
    hosts = (root / "WinUx" / "dialogs" / "native_dock_hosts.py").read_text(encoding="utf-8")
    forms = (root / "WinUx" / "dialogs" / "native_dock_forms.py").read_text(encoding="utf-8")
    assert "def console_complete(" in controller
    assert '"console_complete": controller.console_complete' in callbacks
    assert 'completion_callback=self.callbacks.get("console_complete")' in view
    assert 'self.completion_callback = getattr(panel, "completion_callback", None)' in hosts
    assert 'emit("complete"' in forms and 'command == "completion_result"' in forms


def test_cd_completion_returns_directories_only():
    class ConnectedModel(SSHServerModel):
        @property
        def connected(self):
            return True

    model = ConnectedModel()
    model.home = PurePosixPath("/home/user")
    model._shell_completion_directory = PurePosixPath("/home/user/work")
    model.list_directory = lambda folder: [
        SimpleNamespace(name="Test-17-0285", is_dir=True),
        SimpleNamespace(name="Test-17-0285.com", is_dir=False),
        SimpleNamespace(name="Test-17-0285.inp", is_dir=False),
    ]
    text = "cd Test"
    result = model.complete_shell_input(text, len(text))
    assert result["candidates"] == ["Test-17-0285/"]
    assert result["common_prefix"] == "Test-17-0285/"


def test_multiple_matches_expose_only_safe_common_prefix():
    class ConnectedModel(SSHServerModel):
        @property
        def connected(self):
            return True

    model = ConnectedModel()
    model.home = PurePosixPath("/home/user")
    model._shell_completion_directory = PurePosixPath("/home/user/work")
    model.list_directory = lambda folder: [
        SimpleNamespace(name="Test-17-0285.com", is_dir=False),
        SimpleNamespace(name="Test-17-0285.inp", is_dir=False),
        SimpleNamespace(name="Test-17-0285.log", is_dir=False),
        SimpleNamespace(name="Test-17-0285.que", is_dir=False),
    ]
    text = "ls Test-17"
    result = model.complete_shell_input(text, len(text))
    assert len(result["candidates"]) == 4
    assert result["common_prefix"] == "Test-17-0285."


def test_console_first_tab_uses_common_prefix_before_cmd_style_cycling():
    source = (Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
    completion_body = source.split("    def _completion_result(", 1)[1].split("    def _paste(self):", 1)[0]
    assert 'result.get("common_prefix", "")' in completion_body
    assert '"candidates": candidates, "candidate_index": -1' in completion_body
    assert "self._apply_completion_value(state, common_prefix)" in completion_body
    assert "def _cycle_completion_state" in completion_body
