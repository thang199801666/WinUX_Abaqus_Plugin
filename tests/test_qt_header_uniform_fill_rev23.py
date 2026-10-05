from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "WinUx" / "components"


def read(name):
    return (COMP / name).read_text(encoding="utf-8")


def test_header_background_is_kept_as_a_stable_draw_primitive():
    rendering = read("explorer_rendering.py")
    assert "self._header_background = dpg.draw_rectangle(" in rendering


def test_header_background_tracks_current_viewport_width():
    layout = read("explorer_layout.py")
    assert 'header_background = getattr(self, "_header_background", None)' in layout
    assert "pmax=(header_width, self.HEADER_HEIGHT)" in layout


def test_header_bevel_lines_cover_the_same_full_surface():
    layout = read("explorer_layout.py")
    assert "p2=(header_width, 0.5)" in layout
    assert "p2=(header_width, self.HEADER_HEIGHT - 0.5)" in layout
