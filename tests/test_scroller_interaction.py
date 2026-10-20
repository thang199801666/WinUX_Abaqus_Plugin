"""Exercise visible geometry and pointer gestures without a GUI context."""
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
import unittest

from DearUIQt.qt.scroller import (
    DpgScrollerArrowOverlay, SharedScrollerMetrics, SharedScrollerPalette, dpg_window_rect,
)


class FakeDpg:
    mvMouseButton_Left = 0
    mvAll = 0
    mvStyleVar_WindowPadding = "padding"
    mvStyleVar_ItemSpacing = "spacing"
    mvStyleVar_ChildBorderSize = "border"
    mvThemeCol_ChildBg = "background"
    mvButton = 1
    mvThemeCol_Button = "button"
    mvThemeCol_ButtonHovered = "hovered"
    mvThemeCol_ButtonActive = "active"
    mvStyleVar_FramePadding = "frame_padding"
    mvStyleVar_FrameBorderSize = "frame_border"

    def __init__(self):
        self.items = {"body": {}}
        self.mouse = (0, 0)
        self.down = False
        self.hovered = True
        self.visible = True
        self.hovered_items = {}
        self.active_items = set()
        self.scroll = {"v": 0.0, "h": 0.0}
        self.maximum = {"v": 600.0, "h": 400.0}

    def does_item_exist(self, tag):
        return tag in self.items

    def add_child_window(self, **kwargs):
        self.items[kwargs["tag"]] = kwargs

    add_group = add_child_window
    add_theme = add_child_window
    add_button = add_child_window

    def delete_item(self, tag):
        for child in list(self.items):
            if self.items[child].get("parent") == tag:
                self.delete_item(child)
        self.items.pop(tag, None)

    def add_drawlist(self, width, height, **kwargs):
        self.items[kwargs["tag"]] = dict(width=width, height=height, **kwargs)

    def add_theme_component(self, component, **kwargs):
        return "theme_component"

    def add_theme_style(self, *args, **kwargs):
        pass

    add_theme_color = add_theme_style

    def bind_item_theme(self, item, theme):
        self.items[item]["theme"] = theme

    def move_item(self, item, **kwargs):
        self.items[item]["parent"] = kwargs["parent"]
        if "before" in kwargs:
            self.items[item]["before"] = kwargs["before"]

    def draw_rectangle(self, *args, **kwargs):
        self.items[kwargs["tag"]] = kwargs
        return kwargs["tag"]

    draw_triangle = draw_rectangle

    def configure_item(self, tag, **kwargs):
        self.items[tag].update(kwargs)

    def is_item_shown(self, tag):
        return self.visible and self.items.get(tag, {}).get("show", True)

    def get_item_parent(self, tag):
        return self.items.get(tag, {}).get("parent", 0)

    def get_alias_id(self, tag):
        return tag

    def get_item_state(self, tag):
        # Match DPG child-window state: it has no 'visible' key.
        return self.items.get(tag, {}).get("state", {"hovered": self.hovered})

    def get_item_info(self, tag):
        kind = "mvChildWindow" if tag == "body" else self.items[tag].get("kind", "mvDrawRect")
        return {"type": "mvAppItemType::" + kind}

    def get_all_items(self):
        raise AssertionError("scrollbar must not scan tooltip/popup state")

    def get_item_children(self, tag, slot):
        return self.items.get(tag, {}).get("children", [])

    def get_item_configuration(self, tag):
        return self.items[tag]

    def get_item_rect_size(self, tag):
        return self.get_item_state(tag).get("rect_size", (200, 200))

    def is_item_hovered(self, tag):
        return self.hovered_items.get(tag, self.hovered)

    def is_item_active(self, tag):
        return tag in self.active_items

    def get_mouse_pos(self, **kwargs):
        return self.mouse

    def is_mouse_button_down(self, button):
        return self.down

    def get_y_scroll(self, tag):
        return self.scroll["v"]

    def get_x_scroll(self, tag):
        return self.scroll["h"]

    def get_y_scroll_max(self, tag):
        return self.maximum["v"]

    def get_x_scroll_max(self, tag):
        return self.maximum["h"]

    def set_y_scroll(self, tag, value):
        self.scroll["v"] = value

    def set_x_scroll(self, tag, value):
        self.scroll["h"] = value


class FakeGate:
    def __init__(self):
        self.owner = None
        self.protected = set()

    def register_pointer_protected_item(self, tag):
        self.protected.add(tag)

    def unregister_pointer_protected_item(self, tag):
        self.protected.discard(tag)

    def acquire_pointer_input(self, owner):
        if self.owner is None or self.owner is owner:
            self.owner = owner
            return True
        return False

    def release_pointer_input(self, owner):
        if self.owner is owner:
            self.owner = None


def make_scroller(test):
    dpg = FakeDpg()
    patcher = patch("DearUIQt.qt.scroller.time.monotonic")
    clock = patcher.start()
    test.addCleanup(patcher.stop)
    clock.return_value = 0.0
    overlay = DpgScrollerArrowOverlay(
        dpg, "body", "bar", horizontal=True,
        rect_provider=lambda: (10, 20, 210, 220), interaction_gate=FakeGate())
    test.addCleanup(overlay.destroy)

    def frame(mouse=None, down=None, dt=0.05):
        if mouse is not None:
            dpg.mouse = mouse
        if down is not None:
            dpg.down = down
        clock.return_value += dt
        overlay.update()

    frame()
    return dpg, overlay, frame


def check_hover_expands_and_collapses_without_moving_native_mask(scroller):
    dpg, overlay, frame = scroller
    mask = dict(dpg.items["bar_v_mask"])
    gutter_left = 200 - SharedScrollerMetrics.THICKNESS
    gutter_right = 200
    collapsed_left = gutter_left + (SharedScrollerMetrics.THICKNESS - SharedScrollerMetrics.COLLAPSED_THICKNESS) // 2
    collapsed_right = collapsed_left + SharedScrollerMetrics.COLLAPSED_THICKNESS
    assert dpg.items["bar_v_track"]["pmin"][0] == collapsed_left
    assert dpg.items["bar_v_track"]["pmax"][0] == collapsed_right
    assert (collapsed_left + collapsed_right) / 2 == (gutter_left + gutter_right) / 2
    frame((205, 90))
    assert gutter_left < dpg.items["bar_v_track"]["pmin"][0] < collapsed_left
    assert collapsed_right < dpg.items["bar_v_track"]["pmax"][0] < gutter_right
    for _ in range(4):
        frame()
    assert dpg.items["bar_v_track"]["pmin"][0] == gutter_left
    assert dpg.items["bar_v_track"]["pmax"][0] == gutter_right
    assert dpg.items["bar_v_mask"]["pmin"] == mask["pmin"]
    assert dpg.items["bar_v_mask"]["pmax"] == mask["pmax"]
    assert dpg.items["bar_v_mask"]["show"]
    assert dpg.items["bar_v_track"]["show"]
    assert dpg.items["bar_up_cap"]["show"]
    assert dpg.items["bar_up_arrow"]["show"]
    for _ in range(4):
        frame((0, 0))
    assert dpg.items["bar_v_track"]["pmin"][0] == collapsed_left
    assert dpg.items["bar_v_track"]["pmax"][0] == collapsed_right
    for axis in ("v", "h"):
        assert not dpg.items[f"bar_{axis}_mask"]["show"]
        assert not dpg.items[f"bar_{axis}_track"]["show"]
        assert dpg.items[f"bar_{axis}_thumb"]["show"]
    assert not dpg.items["bar_corner"]["show"]
    # In the desired Explorer-like idle state, the end-arrow affordances fade
    # away together with the hover-expanded track.
    for direction in ("up", "down", "left", "right"):
        assert not dpg.items[f"bar_{direction}_cap"]["show"]
        assert not dpg.items[f"bar_{direction}_arrow"]["show"]
    assert list(dpg.items).index("bar_up_arrow") > list(dpg.items).index("bar_v_mask")


def check_end_buttons(scroller, axis, point):
    dpg, overlay, frame = scroller
    frame(point, True)
    assert dpg.scroll[axis] == 32
    frame(dt=0.2)
    assert dpg.scroll[axis] == 32
    frame(dt=0.2)
    assert dpg.scroll[axis] == 64
    for _ in range(30):
        frame(dt=0.1)
    assert dpg.scroll[axis] == dpg.maximum[axis]
    frame(down=False)
    assert overlay._gesture is None


def check_drag(scroller, axis):
    dpg, overlay, frame = scroller
    thumb = dpg.items[f"bar_{axis}_thumb"]
    center = tuple((a+b)/2 for a, b in zip(thumb["pmin"], thumb["pmax"]))
    center = tuple(value+origin for value, origin in zip(center, overlay._origin))
    frame(center, True)
    assert overlay._gesture["kind"] == "drag"
    # Simulate native ImGui also writing a different scroll value.
    dpg.scroll[axis] = 123
    frame((450, 450))
    assert dpg.scroll[axis] == dpg.maximum[axis]
    frame((0, 0))
    assert dpg.scroll[axis] == 0
    frame(down=False)
    assert overlay._gesture is None


def check_track_pages_and_occluded_target_ignores_press(scroller):
    dpg, overlay, frame = scroller
    dpg.hovered = False
    frame((205, 150), True)
    assert dpg.scroll["v"] == 0
    frame(down=False)
    dpg.hovered = True
    frame((205, 150), True)
    expected_page = overlay._last_axes["v"]["viewport"]
    assert dpg.scroll["v"] == expected_page
    frame(dt=0.5)
    assert dpg.scroll["v"] == expected_page


def check_no_overflow_and_hidden_target_clear_chrome_and_gesture(scroller):
    dpg, overlay, frame = scroller
    frame((205, 204), True)
    dpg.visible = False
    frame()
    assert overlay._gesture is None
    assert not any(config.get("show") for tag, config in dpg.items.items() if tag.startswith("bar_"))
    dpg.visible = True
    dpg.maximum = {"v": 0, "h": 0}
    frame(down=False)
    assert not dpg.items["bar_v_track"]["show"]
    assert not dpg.items["bar_h_track"]["show"]


def check_short_track_keeps_thumb_inside_end_buttons(scroller):
    dpg, overlay, frame = scroller
    overlay.rect_provider = lambda: (10, 20, 60, 65)
    frame()
    thumb = dpg.items["bar_v_thumb"]
    assert thumb["pmin"][1] >= dpg.items["bar_up_cap"]["pmax"][1]
    assert thumb["pmax"][1] <= dpg.items["bar_down_cap"]["pmin"][1]


class ScrollerInteractionTests(unittest.TestCase):
    def test_logical_overflow_shows_thumb_even_when_native_startup_range_is_zero(self):
        dpg, overlay, frame = make_scroller(self)
        dpg.items["canvas"] = dict(width=100, height=20)
        dpg.maximum = {"v": 0, "h": 0}
        size = [600, 360]
        overlay.content_item = "canvas"
        overlay.content_size_provider = lambda: tuple(size)
        frame()
        assert dpg.items["canvas"]["width"] == 600
        assert dpg.items["canvas"]["height"] == 360
        assert dpg.items["bar_h_thumb"]["show"]
        assert dpg.items["bar_v_thumb"]["show"]
        # A stale positive ImGui range must not keep a bar after content fits.
        size[:] = [200, 200]
        dpg.maximum = {"v": 999, "h": 999}
        frame()
        assert not dpg.items["bar_h_thumb"]["show"]
        assert not dpg.items["bar_v_thumb"]["show"]

    def test_content_resize_preserves_scrollbar_gutters_and_horizontal_range_flag(self):
        dpg, overlay, frame = make_scroller(self)
        dpg.configure_item("body", width=200, height=-1, no_scrollbar=False,
                           horizontal_scrollbar=False)
        frame()
        config = dpg.get_item_configuration("body")
        assert config["width"] == -SharedScrollerMetrics.THICKNESS
        assert config["height"] == -SharedScrollerMetrics.THICKNESS
        assert config["no_scrollbar"]
        assert config["horizontal_scrollbar"]
        assert dpg.items["bar_h_thumb"]["show"]

    def test_tooltip_does_not_change_scrollbar_chrome(self):
        dpg, overlay, frame = make_scroller(self)
        dpg.items["tooltip"] = dict(kind="mvTooltip", show=True, children=["tip_text"],
                                    state=dict(visible=True, pos=[0, 0], rect_size=[120, 90]))
        dpg.items["tip_text"] = dict(state=dict(visible=True, pos=[8, 8], rect_min=[180, 170]))
        before = {tag: dict(dpg.items[tag]) for tag in overlay._parts.values()}
        frame()
        assert {tag: dpg.items[tag] for tag in overlay._parts.values()} == before
        dpg.items["tooltip"]["show"] = False
        frame()
        assert {tag: dpg.items[tag] for tag in overlay._parts.values()} == before

    def test_overlapping_window_and_modal_do_not_toggle_chrome(self):
        dpg, overlay, frame = make_scroller(self)
        dpg.items["dialog"] = dict(kind="mvWindowAppItem", show=True,
                                   state=dict(visible=True, pos=[195, 40], rect_size=[70, 80]))
        frame()
        assert dpg.items["bar_v_thumb"]["show"]
        assert dpg.items["bar_h_thumb"]["show"]
        dpg.items["dialog"]["modal"] = True
        dpg.items["dialog"]["state"]["pos"] = [500, 500]
        frame()
        assert dpg.items["bar_h_thumb"]["show"]

    def test_own_window_does_not_occlude_its_scrollbar(self):
        dpg, overlay, frame = make_scroller(self)
        dpg.items[overlay.container]["parent"] = "root"
        dpg.items["root"] = dict(kind="mvWindowAppItem", show=True,
                                 state=dict(visible=True, pos=[0, 0], rect_size=[500, 500]))
        frame()
        assert dpg.items["bar_v_thumb"]["show"]
        assert dpg.items["bar_h_thumb"]["show"]

    def test_window_geometry_skips_groups_and_includes_top_level_offset(self):
        class Windows:
            parents = {"body": "group", "group": "outer", "outer": "window", "window": None}
            types = {"body": "mvChildWindow", "group": "mvGroup",
                     "outer": "mvChildWindow", "window": "mvWindowAppItem"}
            states = {"body": {"pos": [8, 8], "rect_size": [400, 220]},
                      "group": {"pos": [999, 999]},
                      "outer": {"pos": [8, 27], "rect_size": [300, 180]},
                      "window": {"pos": [20, 20], "rect_size": [600, 400]}}

            def get_item_info(self, item):
                return {"type": "mvAppItemType::" + self.types[item]}

            def get_item_state(self, item):
                return self.states[item]

            def get_item_parent(self, item):
                return self.parents[item]

        assert dpg_window_rect(Windows(), "body") == (36, 55, 436, 275)
        # A viewport-front scrollbar must respect the same parent clipping as
        # the native body; its bottom may not spill into a sibling status strip.
        assert dpg_window_rect(Windows(), "body", clip=True) == (36, 55, 328, 227)
        assert dpg_window_rect(Windows(), "group") is None
        windows = Windows()
        windows.states["body"]["pos"] = [8, 200]
        assert dpg_window_rect(windows, "body", clip=True) is None

    def test_hover_animation(self):
        check_hover_expands_and_collapses_without_moving_native_mask(make_scroller(self))

    def test_vertical_buttons(self):
        check_end_buttons(make_scroller(self), "v", (205, 204))

    def test_horizontal_buttons(self):
        check_end_buttons(make_scroller(self), "h", (194, 215))

    def test_vertical_drag(self):
        check_drag(make_scroller(self), "v")

    def test_horizontal_drag(self):
        check_drag(make_scroller(self), "h")

    def test_drawn_thumb_drags_when_parent_window_is_not_hovered(self):
        for axis in ("v", "h"):
            with self.subTest(axis=axis):
                dpg, overlay, frame = make_scroller(self)
                dpg.hovered_items[overlay.container] = False
                check_drag((dpg, overlay, frame), axis)

    def test_native_active_hit_keeps_drag_when_hover_is_lost(self):
        dpg, overlay, frame = make_scroller(self)
        dpg.hovered = False
        dpg.active_items.add(overlay._hits["v"])
        data = overlay._last_axes["v"]
        point = (data["hit"][2] - 2, data["thumb0"] + data["length"] / 2)
        frame(point, True)
        assert overlay._gesture["kind"] == "drag"
        assert overlay._gate().owner is overlay._pointer_owner
        frame((450, 450))
        assert dpg.scroll["v"] == dpg.maximum["v"]
        frame(down=False)
        assert overlay._gate().owner is None

    def test_activation_after_physical_press_poll_still_starts_thumb_drag(self):
        dpg, overlay, frame = make_scroller(self)
        dpg.hovered = False
        data = overlay._last_axes["v"]
        point = (data["hit"][2] - 2, data["thumb0"] + data["length"] / 2)
        frame(point, True)  # hardware down, GLFW has not activated the button yet
        assert overlay._gesture is None
        dpg.active_items.add(overlay._hits["v"])
        frame()
        assert overlay._gesture["kind"] == "drag"
        frame((450, 450))
        assert dpg.scroll["v"] == dpg.maximum["v"]

    def test_native_hit_rects_match_the_painted_gutters(self):
        dpg, overlay, frame = make_scroller(self)
        for axis, tag in overlay._hits.items():
            x0, y0, x1, y1 = overlay._last_axes[axis]["hit"]
            config = dpg.items[tag]
            assert config["pos"] == (x0-overlay._origin[0], y0-overlay._origin[1])
            assert config["width"] == round(x1-x0)
            assert config["height"] == round(y1-y0)
            assert tag in overlay._gate().protected
            assert config["before"] == overlay.anchor

    def test_capture_is_not_stolen_and_is_released_on_hide_destroy_and_range_loss(self):
        dpg, overlay, frame = make_scroller(self)
        gate = overlay._gate()
        other = object()
        gate.owner = other
        frame((205, 204), True)
        assert overlay._gesture is None and gate.owner is other
        frame(down=False)
        gate.owner = None
        for end in ("hide", "range", "destroy"):
            frame((205, 204), True)
            assert gate.owner is overlay._pointer_owner
            if end == "hide":
                overlay.hide()
            elif end == "range":
                dpg.maximum["v"] = 0
                frame()
            else:
                overlay.destroy()
            assert overlay._gesture is None and gate.owner is None
            if end != "destroy":
                dpg.maximum["v"] = 600
                frame(down=False)
        assert not gate.protected
        remaining = dict(dpg.items)
        overlay.update()  # queued visible callback from the disposed owner
        overlay.destroy()
        assert dpg.items == remaining

    def test_native_modal_cancels_capture_without_starting_again_while_held(self):
        dpg, overlay, frame = make_scroller(self)
        frame((205, 204), True)
        gate = overlay._gate()
        assert gate.owner is overlay._pointer_owner
        gate.native_modal_input_active = lambda: True
        frame()
        assert overlay._gesture is None and gate.owner is None
        gate.native_modal_input_active = lambda: False
        frame()
        assert overlay._gesture is None

    def test_registered_modal_suppresses_background_hover_and_gesture(self):
        from DearUIQt.modal import MODAL_TAGS

        dpg, overlay, frame = make_scroller(self)
        # Put the cursor over the vertical scrollbar long enough to reach the
        # fully expanded/hovered visual state first.
        for _ in range(4):
            frame((205, 90))
        assert overlay._expansion["v"] == 1.0
        assert dpg.items["bar_v_thumb"]["fill"] == SharedScrollerPalette.THUMB_HOVER

        # QDialog::show() registers modal windows in MODAL_TAGS.  Even though
        # the global mouse position is still geometrically over this background
        # scrollbar, the foreground dialog must own the visual/input state.
        dpg.items["dialog"] = dict(
            kind="mvWindowAppItem", show=True,
            state=dict(visible=True, pos=[180, 40], rect_size=[100, 100]),
        )
        MODAL_TAGS.add("dialog")
        self.addCleanup(MODAL_TAGS.discard, "dialog")
        frame((205, 90), True)

        assert overlay._expansion["v"] == 0.0
        assert overlay._gesture is None
        assert overlay._gate().owner is None
        assert dpg.items["bar_v_thumb"]["fill"] == SharedScrollerPalette.THUMB

        # Closing the dialog while the mouse is still held must not synthesize
        # a new scrollbar press from the old physical gesture.
        MODAL_TAGS.discard("dialog")
        dpg.items["dialog"]["show"] = False
        frame((205, 90), True)
        assert overlay._gesture is None

    def test_physical_left_release_overrides_cached_dpg_press(self):
        dpg, overlay, frame = make_scroller(self)
        dpg.down = True
        dpg.__name__ = "dearpygui.dearpygui"
        keys = Mock(return_value=0)
        user32 = SimpleNamespace(GetAsyncKeyState=keys)
        with patch("DearUIQt.qt.scroller.os", SimpleNamespace(name="nt")), \
             patch("DearUIQt.qt.scroller.ctypes.windll", SimpleNamespace(user32=user32), create=True):
            assert not overlay._left_button_down()
            keys.assert_called_once_with(1)
            keys.return_value = 0x8000
            assert overlay._left_button_down()

    def test_page_and_occlusion(self):
        check_track_pages_and_occluded_target_ignores_press(make_scroller(self))

    def test_hidden_and_no_overflow(self):
        check_no_overflow_and_hidden_target_clear_chrome_and_gesture(make_scroller(self))

    def test_small_viewport(self):
        check_short_track_keeps_thumb_inside_end_buttons(make_scroller(self))
