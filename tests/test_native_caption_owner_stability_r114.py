from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import DearUIQt.backends.native_windows as native_windows
from DearUIQt.backends.native_windows import NativeWindowBackend


ROOT = Path(__file__).resolve().parents[1]


def _extension(handles):
    def handle(tag):
        return handles.get(int(tag), 0)

    return SimpleNamespace(
        dearuiqt_enable_native_windows=Mock(return_value=True),
        dearuiqt_native_windows_enabled=Mock(return_value=True),
        dearuiqt_configure_native_window=Mock(),
        dearuiqt_native_window_handle=Mock(side_effect=handle),
    )


class _FakeUser32:
    def __init__(self, owner=0):
        self.owner = int(owner)
        self.GetWindow = Mock(side_effect=self._get_window)
        self.SetWindowLongPtrW = Mock(side_effect=self._set_owner)
        self.SetWindowLongW = Mock(side_effect=self._set_owner)

    def _get_window(self, _hwnd, relation):
        assert int(relation) == 4  # GW_OWNER
        return self.owner

    def _set_owner(self, _hwnd, index, value):
        assert int(index) == -8  # GWLP_HWNDPARENT
        self.owner = int(getattr(value, "value", value))
        return 0


def test_python_owner_sync_writes_only_when_owner_changes(monkeypatch):
    extension = _extension({12: 1234})
    backend = NativeWindowBackend(SimpleNamespace(internal_dpg=extension))
    backend.configure(12, modal=True, owner_hwnd=5678)
    user32 = _FakeUser32(owner=0)
    monkeypatch.setattr(native_windows, "_windows_user32", lambda: user32)

    assert backend.synchronizeOwner(12) is True
    assert user32.owner == 5678
    assert user32.SetWindowLongPtrW.call_count == 1

    # A second frame/query must not rewrite the owner.  Rewriting it is what
    # resets Windows' non-client hot state and made the Close button blink.
    assert backend.synchronizeOwner(12) is True
    assert user32.SetWindowLongPtrW.call_count == 1


def test_nested_native_owner_resolves_from_owner_viewport(monkeypatch):
    extension = _extension({12: 1234, 13: 5678})
    backend = NativeWindowBackend(SimpleNamespace(internal_dpg=extension))
    backend.configure(12, owner=SimpleNamespace(tag=13), modal=True)
    user32 = _FakeUser32(owner=0)
    monkeypatch.setattr(native_windows, "_windows_user32", lambda: user32)

    assert backend.synchronizeOwner(12) is True
    assert user32.owner == 5678
    assert user32.SetWindowLongPtrW.call_count == 1


def test_native_source_does_not_rewrite_owner_every_render():
    source = (ROOT / "DearUIQt/native/dearuiqt_native_windows.h").read_text(encoding="utf-8")
    assert "if (GetWindow(handle, GW_OWNER) != parent)" in source
    assert "SetWindowLongPtrW(handle, GWLP_HWNDPARENT" in source


def test_bundled_runtime_patch_hash_is_self_consistent():
    runtime = ROOT / "DearUIQt/native/runtime/cp310-win_amd64"
    binary = runtime / "dearpygui/_dearpygui.pyd"
    metadata = json.loads((runtime / "dearuiqt_build.json").read_text(encoding="utf-8"))
    assert metadata.get("runtime_patch") == "owner-sync-caption-only-drag-r121"
    assert metadata["extension_sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
