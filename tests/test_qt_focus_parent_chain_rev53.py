"""Static regressions for Qt-like focus ownership and nested dialog handoff."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIALOG = (ROOT / "DearUIQt/dialogs/qt_dialog.py").read_text(encoding="utf-8")
HOST = (ROOT / "WinUx/ui/native/native_dialog_host.py").read_text(encoding="utf-8")


def test_active_window_includes_focused_descendants():
    assert "def isActiveWindow(self):" in DIALOG
    assert "self._item_belongs_to(focused, self.tag)" in DIALOG
    assert "not dialog.isActiveWindow()" in DIALOG


def test_qdialog_exposes_qt_tab_chain_primitives():
    assert "def focusWidget(self):" in DIALOG
    assert "def setTabOrder(self, first, second):" in DIALOG
    assert "def focusNextPrevChild(self, next=True):" in DIALOG
    assert 'key == getattr(dpg, "mvKey_Tab", None)' in DIALOG
    assert "next=not shift" in DIALOG


def test_explicit_shortcut_precedes_generic_tab_traversal():
    dispatch = DIALOG.split("def _dispatch_key", 1)[1].split("def _dispatch_return", 1)[0]
    assert dispatch.index("shortcut = dialog.shortcuts") < dispatch.index("mvKey_Tab")


def test_nested_focus_return_prefers_logical_parent():
    restore = DIALOG.split("def _restore_embedded_owner_focus", 1)[1].split("def delete_owned_item", 1)[0]
    assert "parent = self.parent" in restore
    assert "isinstance(parent, QtDialog)" in restore
    assert "self._item_belongs_to(target, parent.tag)" in restore


def test_modeless_background_close_does_not_steal_focus():
    hide = DIALOG.split("    def hide(self):", 1)[1].split("    def event(self, event):", 1)[0]
    focus_expr = hide.split("self._restore_focus_on_hide = bool(", 1)[1].split(")", 1)[0]
    assert "self.modal or self._item_belongs_to(focused_item, self.tag)" in hide
    assert "_activation_owned" not in focus_expr


def test_modal_owner_releases_capture_from_native_child_hwnd():
    release = HOST.split("def release_owner_mouse_capture", 1)[1].split("def _acquire_modal_owner", 1)[0]
    assert "GetAncestor" in release
    assert "capture_root" in release
    assert "capture_root != owner_hwnd" in release


def test_enter_and_escape_route_only_to_active_modeless_dialog():
    base = (ROOT / "DearUIQt/dialogs/base.py").read_text(encoding="utf-8")
    assert "active_when" in base
    assert "not bool(active_when())" in base
    assert "dialog.modal or dialog.isActiveWindow()" in DIALOG
    assert "self._accepts_dialog_keys" in DIALOG
