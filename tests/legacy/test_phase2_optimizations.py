"""Phase-2 regression guards for behavior-preserving hot-path optimizations."""
from pathlib import Path

from WinUx.runtime.terminal_buffer import TerminalBuffer


ROOT = Path(__file__).resolve().parents[1]


def test_terminal_viewport_styles_match_legacy_full_layout():
    buffer = TerminalBuffer()
    buffer.set_output("plain\n\x1b[31merror\x1b[0m\nwarning\n$ ")
    buffer.type_text("status --all")
    full, cursor_row, cursor_column = buffer.styled_layout(12)
    viewport, slice_cursor_row, slice_cursor_column = buffer.styled_layout_slice(12, 1, 4)
    assert viewport == full[1:4]
    assert (slice_cursor_row, slice_cursor_column) == (cursor_row, cursor_column)


def test_console_renderer_uses_viewport_styling_api():
    source = (ROOT / "WinUx" / "ui" / "components" / "console_renderer.py").read_text(encoding="utf-8")
    assert "view.buffer.styled_layout_slice(columns, first, last)" in source
    assert "view.buffer.layout(columns)" in source


def test_plot_layout_has_dirty_signature_and_no_duplicate_waiting_sync():
    source = (ROOT / "WinUx" / "ui" / "components" / "job_plots.py").read_text(encoding="utf-8")
    assert "self._client_layout_signature = None" in source
    assert "signature == self._client_layout_signature" in source
    waiting = source[source.index("def set_waiting"):source.index("def set_status")]
    assert waiting.count("_set_status_message") == 1
    assert "_sync_client_layout()\n            self._sync_client_layout()" not in source
