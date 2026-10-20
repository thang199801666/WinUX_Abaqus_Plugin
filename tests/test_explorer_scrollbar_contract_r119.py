from DearUIQt.backends.dearpygui_scroller import SharedScrollerMetrics, SharedScrollerPalette


def test_shared_scroller_uses_windows_explorer_like_geometry_contract():
    m = SharedScrollerMetrics
    assert m.THICKNESS == 10
    assert m.COLLAPSED_THICKNESS == 4
    assert m.COLLAPSED_THICKNESS < m.THICKNESS
    assert m.ROUNDING == 4
    assert m.MIN_THUMB >= 22
    assert m.ARROW_GLYPH_RADIUS == 2.7


def test_shared_scroller_palette_prefers_light_track_and_neutral_thumb():
    p = SharedScrollerPalette
    assert p.TRACK[:3] == (250, 250, 250)
    assert p.THUMB[:3] == (162, 162, 162)
    assert p.THUMB_HOVER[:3] == (142, 142, 142)
    assert p.THUMB_ACTIVE[:3] == (122, 122, 122)
    assert p.ARROW[:3] == (92, 92, 92)
    assert p.ARROW[3] == 255
    assert p.ARROW_DISABLED[3] == 255


def test_scroller_triangle_points_snap_to_integer_pixels_for_crisp_rendering():
    from DearUIQt.backends.dearpygui_scroller import DpgScrollerArrowOverlay

    for direction in ("up", "down", "left", "right"):
        points = DpgScrollerArrowOverlay._triangle(10.4, 12.6, direction, 2.7)
        assert len(points) == 3
        for x, y in points:
            assert isinstance(x, int)
            assert isinstance(y, int)


def test_scroller_rectangles_snap_to_integer_pixels_for_crisp_tracks_and_thumbs():
    from DearUIQt.backends.dearpygui_scroller import DpgScrollerArrowOverlay

    snapped = DpgScrollerArrowOverlay._snap_rect((10.4, 12.6, 20.2, 31.8), (1.1, 2.2))
    assert snapped == (9, 10, 19, 30)


def test_scroller_centers_collapse_in_real_layout_lane_not_fixed_right_edge():
    from DearUIQt.backends.dearpygui_scroller import DpgScrollerArrowOverlay

    # Parent right edge is 210, while the scrolling child actually ends at 196.
    # The real lane is therefore 14 px wide (196..210), not the nominal 10 px.
    lane = DpgScrollerArrowOverlay._resolve_lane(10, 210, 196, 10)
    assert lane == (196.0, 210.0)
    collapsed = DpgScrollerArrowOverlay._centered_span(*lane, 4)
    assert collapsed == (201.0, 205.0)
    assert sum(collapsed) / 2.0 == sum(lane) / 2.0


def test_scroller_falls_back_to_nominal_lane_when_child_geometry_is_invalid():
    from DearUIQt.backends.dearpygui_scroller import DpgScrollerArrowOverlay

    assert DpgScrollerArrowOverlay._resolve_lane(10, 210, None, 10) == (200.0, 210.0)
    assert DpgScrollerArrowOverlay._resolve_lane(10, 210, 120, 10) == (200.0, 210.0)


def test_scroller_arrow_triangle_is_slightly_larger():
    from DearUIQt.backends.dearpygui_scroller import DpgScrollerArrowOverlay, SharedScrollerMetrics

    points = DpgScrollerArrowOverlay._triangle(10, 10, "up", SharedScrollerMetrics.ARROW_GLYPH_RADIUS)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    assert max(xs) - min(xs) >= 6
    assert max(ys) - min(ys) >= 4
