"""Regression contract for stable native Windows caption Close hover."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWPORT = ROOT / "WinUx" / "ui" / "native" / "floating_viewport.py"


def test_native_caption_close_hover_ignores_only_stale_nonclient_leave():
    source = VIEWPORT.read_text(encoding="utf-8")
    assert "WM_NCMOUSEMOVE = 0x00A0" in source
    assert "WM_NCMOUSELEAVE = 0x02A2" in source
    assert "HTCLOSE = 20" in source
    handler = source.split("def install_close_handler", 1)[1].split(
        "def restore_close_handler", 1)[0]
    assert "self._caption_close_hover = int(wparam) == HTCLOSE" in handler
    assert "_cursor_is_still_over_native_close(hwnd)" in handler
    assert "return 0" in handler


def test_stale_leave_filter_requires_foreground_enabled_window_and_live_hit_test():
    source = VIEWPORT.read_text(encoding="utf-8")
    helper = source.split("def _cursor_is_still_over_native_close", 1)[1].split(
        "def procedure", 1)[0]
    assert "GetForegroundWindow" in helper
    assert "IsWindowEnabled" in helper
    assert "SendMessageW" in helper
    assert "WM_NCHITTEST" in helper
    assert "== HTCLOSE" in helper


def test_caption_hover_state_is_reset_when_native_hook_is_removed():
    source = VIEWPORT.read_text(encoding="utf-8")
    restore = source.split("def restore_close_handler", 1)[1]
    assert "self._caption_close_hover = False" in restore
