from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from WinUx.server_model import SSHServerModel


class ConnectedModel(SSHServerModel):
    @property
    def connected(self):
        return True


def _model(items=()):
    model = ConnectedModel()
    model.home = PurePosixPath("/home/user")
    model._shell_completion_directory = PurePosixPath("/home/user/work")
    model.list_directory = lambda folder: list(items)
    return model


def test_mid_token_completion_replaces_the_whole_shell_word():
    text = "ls Test-old.log"
    cursor = text.index("-")
    ctx = SSHServerModel._completion_word_context(text, cursor)
    assert ctx["start"] == 3
    assert ctx["end"] == len(text)
    assert ctx["value"] == "Test"


def test_unique_file_completion_appends_space_but_directory_keeps_slash():
    file_model = _model([SimpleNamespace(name="Test.inp", is_dir=False)])
    result = file_model.complete_shell_input("cat Te", len("cat Te"))
    assert result["candidates"] == ["Test.inp"]
    assert result["replacement"] == "Test.inp "

    dir_model = _model([SimpleNamespace(name="Tests", is_dir=True)])
    result = dir_model.complete_shell_input("cd Te", len("cd Te"))
    assert result["candidates"] == ["Tests/"]
    assert result["replacement"] == "Tests/"


def test_cd_ambiguity_never_includes_regular_files():
    model = _model([
        SimpleNamespace(name="Test-A", is_dir=True),
        SimpleNamespace(name="Test-B", is_dir=True),
        SimpleNamespace(name="Test-A.inp", is_dir=False),
        SimpleNamespace(name="Test-A.log", is_dir=False),
    ])
    result = model.complete_shell_input("cd T", len("cd T"))
    assert result["candidates"] == ["Test-A/", "Test-B/"]
    assert result["common_prefix"] == "Test-"


def test_completion_grid_is_readline_like_and_width_bounded():
    values = ["alpha", "beta", "gamma", "delta"]
    text = SSHServerModel._format_completion_candidates(values, columns=24)
    lines = text.split("\r\n")
    assert len(lines) == 2
    assert all(len(line) <= 24 for line in lines)
    assert "alpha" in text and "delta" in text


def test_completion_listing_redraws_prompt_without_sending_to_pty():
    model = _model()
    model._shell_visible_output.append("[user@host work]$ ")
    assert model.append_shell_completion_listing(
        "ls Te", ["Test-A", "Test-B"], columns=40)
    visible = model.shell_output()
    assert "[user@host work]$ ls Te" in visible
    assert "Test-A" in visible and "Test-B" in visible
    assert visible.endswith("[user@host work]$ ")


def test_console_uses_cmd_style_candidate_cycling_after_common_prefix():
    source = (Path(__file__).resolve().parents[1] / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
    tab_body = source.split("    def _tab(self):", 1)[1].split("    def _completion_result(", 1)[0]
    result_body = source.split("    def _completion_result(", 1)[1].split("    def _apply_completion_value", 1)[0]
    assert "_cycle_completion_state(state, direction)" in tab_body
    assert "_completion_queued_directions.append(direction)" in tab_body
    assert "common_prefix" in result_body
    assert "_cycle_completion_state(state, queued_direction)" in result_body


def test_completion_list_is_wired_for_embedded_and_floating_console():
    root = Path(__file__).resolve().parents[1]
    controller = (root / "WinUx" / "controller.py").read_text(encoding="utf-8")
    callbacks = (root / "WinUx" / "controllers" / "callbacks.py").read_text(encoding="utf-8")
    view = (root / "WinUx" / "view.py").read_text(encoding="utf-8")
    forms = (root / "WinUx" / "dialogs" / "native_dock_forms.py").read_text(encoding="utf-8")
    hosts = (root / "WinUx" / "dialogs" / "native_dock_hosts.py").read_text(encoding="utf-8")
    floating = (root / "WinUx" / "dialogs" / "floating_adapters.py").read_text(encoding="utf-8")
    assert "def console_completion_list(" in controller
    assert '"console_completion_list": controller.console_completion_list' in callbacks
    assert 'completion_list_callback=self.callbacks.get("console_completion_list")' in view
    assert 'emit("completion_list"' in forms
    assert 'self.completion_list_callback = getattr(panel, "completion_list_callback", None)' in hosts
    assert 'event == "completion_list"' in floating
