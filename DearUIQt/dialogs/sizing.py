"""Font-metric-driven size hints for lightweight message and input dialogs.

The layout contract deliberately derives geometry from the active font instead
of fixed Segoe-UI-era pixel assumptions.  This keeps dialogs stable when WinUx
changes application family/size at runtime.
"""
from __future__ import annotations


_MIN_DIALOG_WIDTH = 360
_MAX_DIALOG_WIDTH = 680
_MAX_DIALOG_HEIGHT = 560
_ICON_COLUMN_WIDTH = 42
_HORIZONTAL_CHROME = 76  # window padding + icon/text gap + safety margin
_VERTICAL_CHROME = 96    # caption/body/footer margins not represented by text
_MIN_BUTTON_FOOTER = 48


def _metric_height(metrics, fallback=14):
    try:
        return max(1, int(metrics.lineSpacing()))
    except Exception:
        return int(fallback)


def _advance(metrics, text, fallback_px=7):
    try:
        return max(0, int(metrics.horizontalAdvance(str(text or ""))))
    except Exception:
        return max(0, len(str(text or "")) * int(fallback_px))


def _wrapped_lines(metrics, text, width):
    value = str(text or "")
    try:
        return tuple(metrics.wrappedLines(value, max(1, int(width))))
    except Exception:
        # Conservative fallback used only by renderer-less tests/hosts.
        avg = max(1, _advance(metrics, "ABCDEFGHIJKLMNOPQRSTUVWXYZ") // 26)
        columns = max(8, int(width) // avg)
        out = []
        for paragraph in (value.split("\n") or [""]):
            if not paragraph:
                out.append("")
                continue
            words = paragraph.split()
            line = ""
            for word in words:
                candidate = word if not line else line + " " + word
                if len(candidate) <= columns:
                    line = candidate
                else:
                    if line:
                        out.append(line)
                    line = word
            out.append(line)
        return tuple(out or [""])


def _natural_text_width(metrics, text):
    return max((_advance(metrics, line) for line in str(text or "").split("\n")), default=0)


def compact_message_size(message, *, heading="", kind="message", width=None,
                         body_metrics=None, heading_metrics=None,
                         min_width=_MIN_DIALOG_WIDTH, max_width=_MAX_DIALOG_WIDTH,
                         max_height=_MAX_DIALOG_HEIGHT):
    """Return a QMessageBox-like size hint derived from active font metrics.

    ``body_metrics`` / ``heading_metrics`` are normally ``QFontMetrics`` for
    the actual fonts bound to the dialog.  Width, wrapped line count and height
    therefore track the selected application font and font size.
    """
    body_metrics = body_metrics or heading_metrics
    heading_metrics = heading_metrics or body_metrics

    body_line = _metric_height(body_metrics, 14)
    heading_line = _metric_height(heading_metrics, body_line)

    if width is None:
        natural = max(
            _natural_text_width(body_metrics, message),
            _natural_text_width(heading_metrics, heading),
        )
        width = natural + _ICON_COLUMN_WIDTH + _HORIZONTAL_CHROME
    width = max(int(min_width), min(int(max_width), int(width)))

    text_width = max(120, width - _ICON_COLUMN_WIDTH - _HORIZONTAL_CHROME)
    body_lines = _wrapped_lines(body_metrics, message, text_width)
    heading_lines = _wrapped_lines(heading_metrics, heading, text_width)

    heading_height = max(heading_line, len(heading_lines) * heading_line)
    body_height = max(body_line, len(body_lines) * body_line)
    text_gap = max(2, int(round(body_line * 0.22)))
    content_height = max(36, heading_height + text_gap + body_height)

    # Keep all non-text geometry proportional to the active text line height.
    vertical_padding = max(18, int(round(body_line * 1.30)))
    footer_height = max(_MIN_BUTTON_FOOTER, int(round(body_line * 2.85)))
    editor_height = max(30, int(round(body_line * 2.0))) if kind == "input" else 0
    # Dear ImGui tables/groups add row/item spacing around the measured text
    # block. Account for that chrome up front so compact QMessageBox-style
    # dialogs fit their contents without producing a tiny vertical scroll range.
    renderer_spacing = max(12, int(round(body_line * 1.05)))
    height = (content_height + vertical_padding + footer_height + editor_height
              + renderer_spacing)
    return width, min(int(max_height), max(136, int(height)))


__all__ = ["compact_message_size"]
