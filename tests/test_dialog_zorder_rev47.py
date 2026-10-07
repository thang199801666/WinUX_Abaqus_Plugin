from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "WinUx" / "platform" / "native_dialog_host.py"
VIEWPORT = ROOT / "WinUx" / "platform" / "floating_viewport.py"
DIALOG = ROOT / "WinUx" / "dialogs" / "floating_dialog.py"


def test_genuine_close_handoff_uses_one_shot_non_topmost_zorder_repair():
    source = HOST.read_text(encoding="utf-8")
    body = source.split("def handoff_owner_before_close", 1)[1].split("def restore_owner_focus", 1)[0]
    assert "raise_z_order=True" in body
    assert "TOPMOST" in body  # documentation explicitly says it is not topmost


def test_open_activation_keeps_cross_process_owner_dialog_stack_together():
    host = HOST.read_text(encoding="utf-8")
    viewport = VIEWPORT.read_text(encoding="utf-8")
    assert "def prepare_owned_dialog_stack" in host
    helper = host.split("def prepare_owned_dialog_stack", 1)[1].split("def handoff_owner_before_close", 1)[0]
    assert "SWP_NOACTIVATE" in helper
    assert "SetWindowPos(owner" in helper
    assert "SetWindowPos(dialog" in helper
    activate = viewport.split("def activate(self):", 1)[1].split("def install_close_handler", 1)[0]
    assert "prepare_owned_dialog_stack(self._owner_hwnd, self.hwnd)" in activate


def test_floating_dialog_prefers_exact_main_viewport_hwnd_from_view():
    source = DIALOG.read_text(encoding="utf-8")
    block = source.split("self._owner_acquired = False", 1)[1].split("self._visible", 1)[0]
    assert '_find_main_viewport_hwnd' in block
    assert 'resolved_owner or find_process_window("WinUX")' in block


def test_native_qdialog_maps_and_activates_before_disabling_owner():
    source = HOST.read_text(encoding="utf-8")
    body = source.split("def _handle_window_lifecycle", 1)[1].split("def _handle_window_command", 1)[0]
    show = body.split("self._set_native_modal_input(True)", 1)[1]
    deiconify = show.index("window.deiconify()")
    stack = show.index("prepare_owned_dialog_stack(owner_hwnd, dialog_hwnd)")
    disable = show.index("self._set_modal_owner_active(True)")
    assert deiconify < stack < disable


def test_native_dialog_controller_prefers_main_viewport_hwnd_resolver():
    source = HOST.read_text(encoding="utf-8")
    block = source.split("class NativeDialogController", 1)[1].split("@property", 1)[0]
    assert '_find_main_viewport_hwnd' in block
    assert 'resolved_owner or find_process_window("WinUX")' in block


def test_native_login_keeps_owner_and_dialog_in_same_stack_on_publish_and_show():
    source = (ROOT / "WinUx" / "dialogs" / "native_login_runtime.py").read_text(encoding="utf-8")
    assert "prepare_owned_dialog_stack" in source
    assert source.count("prepare_owned_dialog_stack(self.owner_hwnd, self.hwnd)") >= 3
