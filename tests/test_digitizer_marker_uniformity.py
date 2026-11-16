import math

from WinUx.plotdigitizer.ui.markers import marker_metrics


def test_manual_and_automatic_markers_have_identical_metrics():
    for zoom in (0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 16.0):
        for scale in (0.5, 1.0, 1.75, 2.5):
            auto = marker_metrics(zoom, 'auto', scale)
            manual = marker_metrics(zoom, 'manual', scale)
            assert auto == manual


def test_marker_metrics_are_finite_and_bounded_for_invalid_zoom():
    for zoom in (0, -1, float('nan'), float('inf')):
        metrics = marker_metrics(zoom, 'manual', 1.0)
        assert math.isfinite(metrics.radius)
        assert 2.0 <= metrics.radius <= 5.5
        assert metrics.selection_radius >= metrics.radius
        assert metrics.hit_radius >= metrics.radius
