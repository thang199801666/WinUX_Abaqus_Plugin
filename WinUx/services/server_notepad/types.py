from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


_EOL_NAMES = {
    "\r\n": "Windows (CR LF)",
    "\n": "Unix (LF)",
    "\r": "Macintosh (CR)",
}
_ENCODING_LABELS = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 BOM",
    "utf-16-le-bom": "UTF-16 LE BOM",
    "utf-16-be-bom": "UTF-16 BE BOM",
    "latin-1": "ANSI (Latin-1)",
}
_ENCODING_VALUES = {label: value for value, label in _ENCODING_LABELS.items()}


@dataclass
class _Document:
    path: str
    encoding: str
    signature: dict
    original_text: str
    original_encoding: str
    eol: str
    original_eol: str
    size: int = 0
    language: str = "Normal Text"
    conflict: bool = False
    busy: bool = False
    pending_operation: str = ""
    frame: object = None
    editor_frame: object = None
    text: object = None
    line_numbers: object = None
    line_numbers_after: object = None
    yscroll: object = None
    xscroll: object = None
    highlight_after: object = None
    status_message: str = "Ready"
    last_find: str = ""
    last_find_options: dict = field(default_factory=dict)
    loaded: bool = False
    loading: bool = False
    queued: bool = False
    session_restore: bool = False
    load_text: str = ""
    load_offset: int = 0
    load_label: str = "Loaded"
    highlight_generation: int = 0
    highlight_snapshot: object = None
    dirty: bool = False
    stream_expected_chars: int = 0
    stream_received_chars: int = 0
    stream_pending_cr: str = ""
    stream_operation: str = ""
    line_count: int = 1
    current_line_start: str = ""
    load_seconds: float = 0.0
    stream_expected_bytes: int = 0
    stream_received_bytes: int = 0
    rendered_chars: int = 0
    render_chunks: object = field(default_factory=deque)
    render_after: object = None
    stream_end_pending: bool = False
    stream_end_meta: dict = field(default_factory=dict)
    performance_mode: bool = False
    bookmarks: set = field(default_factory=set)
    last_progress_ui: float = 0.0
    snapshot_parts: object = field(default_factory=list)
    snapshot_text: str = ""
    line_offsets: object = field(default_factory=list)
    function_entries: object = field(default_factory=list)
    index_ready: bool = False
    index_generation: int = 0
    render_slice_chars: int = 64 * 1024
    last_render_ms: float = 0.0
    save_export_parts: object = field(default_factory=list)
    save_export_index: str = "1.0"
    save_force: bool = False
    save_export_generation: int = 0
    save_export_chars: int = 0
