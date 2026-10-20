from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "WinUx" / "view.py"
FLOATING = ROOT / "WinUx" / "ui" / "hosting" / "floating_dialog.py"


def test_startup_transfer_prewarm_refills_pool_without_creating_hidden_owned_dialog():
    source = VIEW.read_text(encoding="utf-8")
    block = source.split("    def _prewarm_transfer_center(self):", 1)[1].split("    def _prewarm_inprocess_dialog_imports", 1)[0]
    # Idle prewarm is dual-mode.  The default in-process path builds one
    # retained Qt-style tool during an idle turn (no secondary HWND exists),
    # while legacy process-host mode refills the bounded floating host pool
    # instead of ever constructing a hidden owned floating dialog.
    assert "if _use_inprocess_dialogs():" in block
    assert "self._get_transfer_center().hide()" in block
    assert "return" in block
    assert "dialog_host_manager(self).refill()" in block
    # Idle preparation is optional and must never affect the main HWND.
    assert "except Exception:" in block
    assert "log_exception(" in block
    hidden_floating = "open_floating_dialog(" in block
    assert not hidden_floating


def test_floating_pointer_surface_is_registered_only_after_confirmed_visibility():
    source = FLOATING.read_text(encoding="utf-8")
    accept = source.split("    def _accept_native_hwnd(self, message):", 1)[1].split("    def handle_event", 1)[0]
    confirm = source.split("    def _confirm_visibility(self, visible, return_focus=False):", 1)[1].split("    def _release_visibility_guards", 1)[0]
    assert 'if getattr(self, "_native_visible", False):' in accept
    assert "register_native_pointer_surface(hwnd)" in accept
    assert "if self._hwnd:" in confirm
    assert "if visible:" in confirm
    assert "register_native_pointer_surface(self._hwnd)" in confirm
    assert "unregister_native_pointer_surface(self._hwnd)" in confirm
