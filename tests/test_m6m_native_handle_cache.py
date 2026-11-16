"""M6m native HWND/owner cache regressions."""
from pathlib import Path
from types import SimpleNamespace

from DearUIQt.backends.native_windows import NativeWindowBackend

ROOT = Path(__file__).resolve().parents[1]


class _FakeNativeBackend:
    def __init__(self):
        self.aliases = {"dialog": 202, "owner": 101}
        self.handles = {202: 5002, 101: 5001}
        self.handle_calls = 0
        self.configured = []

    def get_alias_id(self, alias):
        return self.aliases.get(alias, 0)

    def dearuiqt_enable_native_windows(self):
        return True

    def dearuiqt_native_windows_enabled(self):
        return True

    def dearuiqt_configure_native_window(self, tag, owner_tag, modal):
        self.configured.append((tag, owner_tag, bool(modal)))
        return True

    def dearuiqt_native_window_handle(self, tag):
        self.handle_calls += 1
        return self.handles.get(tag, 0)


def test_raw_winid_reuses_cached_handle_until_configure_invalidates_it():
    backend = _FakeNativeBackend()
    native = NativeWindowBackend(backend)
    dialog = SimpleNamespace(tag="dialog")
    owner = SimpleNamespace(tag="owner")

    native.configure(dialog, owner=owner)
    assert native._rawWinId(dialog) == 5002
    assert native._rawWinId(dialog) == 5002
    assert backend.handle_calls == 1

    native.configure(dialog, owner=owner)
    assert native._rawWinId(dialog) == 5002
    assert backend.handle_calls == 2


def test_source_contains_resolved_owner_fast_path():
    source = (ROOT / "DearUIQt" / "backends" / "native_windows.py").read_text()
    helper = source[source.index("def _synchronizeOwnerResolved"):
                    source.index("def synchronizeOwner")]
    winid = source[source.index("def winId"):
                   source.index("def setCloseRequestHandler")]
    assert "cached_relation == (hwnd, owner_hwnd)" in helper
    assert "self._synchronizeOwnerResolved(tag, hwnd, owner_hwnd)" in winid
    assert "self.synchronizeOwner(item)" not in winid


def test_destroyed_handle_cleanup_covers_chrome_and_interaction_state():
    source = (ROOT / "DearUIQt" / "backends" / "native_windows.py").read_text()
    block = source[source.index("def _forgetNativeHandleState"):
                   source.index("def _invalidateNativeHandle")]
    assert "_native_resize_style_bits.pop" in block
    assert "_dialog_chrome_policy.pop" in block
    assert "_mouse_activate_hooks.pop" in block
    assert "_owner_relation_cache.pop" in block
