from DearUIQt.gui.style import (
    METRICS, metrics_for_backend, set_application_typography, clear_application_typography,
)


class FontMetricBackend:
    def __init__(self, line_height):
        self.line_height = line_height

    def get_text_size(self, text, **kwargs):
        return (max(1, len(str(text))) * 7, self.line_height)


def test_application_font_line_height_expands_control_chrome():
    backend = FontMetricBackend(24)
    try:
        set_application_typography(backend, object())
        metrics = metrics_for_backend(backend)
        assert metrics.control_height > METRICS.control_height
        assert metrics.button_height >= metrics.control_height
        assert metrics.row_height >= 24
        assert metrics.header_height >= 24
    finally:
        clear_application_typography(backend)


def test_default_line_height_preserves_existing_control_dimensions():
    backend = FontMetricBackend(15)
    try:
        set_application_typography(backend, object())
        metrics = metrics_for_backend(backend)
        assert metrics.control_height == METRICS.control_height
        assert metrics.button_height == METRICS.button_height
    finally:
        clear_application_typography(backend)
