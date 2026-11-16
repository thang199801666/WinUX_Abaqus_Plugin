"""Theme-aware Job Viewer scheduler-status presentation."""
from __future__ import annotations

from DearUIQt.gui.palette import set_color_scheme
from WinUx.ui.components.jobs_view import JobsView


def test_job_status_rows_preserve_light_palette_and_use_dark_semantic_surfaces():
    try:
        set_color_scheme("Light")
        assert JobsView.status_row_fill("Running") == (205, 244, 213, 255)
        assert JobsView.status_row_fill("R") == (205, 244, 213, 255)
        assert JobsView.status_row_fill("Queued") == (255, 237, 213, 255)
        assert JobsView.status_row_fill("Q") == (255, 237, 213, 255)
        assert JobsView.status_row_text_color("Running") == (31, 41, 34, 255)

        set_color_scheme("Dark")
        running = JobsView.status_row_fill("Running")
        queued = JobsView.status_row_fill("Queued")
        assert running == (31, 78, 47, 255)
        assert queued == (92, 65, 27, 255)
        assert sum(running[:3]) < 255
        assert sum(queued[:3]) < 255
        assert JobsView.status_row_text_color("Running") == (245, 248, 246, 255)
        assert JobsView.status_row_text_color("Queued") == (245, 248, 246, 255)
        assert JobsView.status_row_fill("Finished") is None
        assert JobsView.status_row_text_color("Finished") is None
    finally:
        set_color_scheme("Light")


def test_job_status_visuals_rebind_both_fill_and_foreground_after_theme_change():
    class Item:
        def __init__(self):
            self.data = {"status": "Running"}

    item = Item()
    try:
        set_color_scheme("Light")
        JobsView.apply_status_visuals(item)
        assert item.data["row_fill"] == (205, 244, 213, 255)
        assert item.data["row_text_color"] == (31, 41, 34, 255)

        set_color_scheme("Dark")
        JobsView.apply_status_visuals(item)
        assert item.data["row_fill"] == (31, 78, 47, 255)
        assert item.data["row_text_color"] == (245, 248, 246, 255)
    finally:
        set_color_scheme("Light")


def test_explorer_renderer_tracks_semantic_row_text_color():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    rendering = (root / "WinUx/ui/components/explorer/rendering.py").read_text(encoding="utf-8")
    assert 'item.data.get("row_text_color")' in rendering
    assert 'row["visual_text_color"] = None' in rendering
