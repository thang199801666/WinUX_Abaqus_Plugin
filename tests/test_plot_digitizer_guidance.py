import sys
import time
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw


pytestmark = [pytest.mark.windows_native,
              pytest.mark.skipif(sys.platform != "win32", reason="Requires native DearPyGui")]


@pytest.fixture
def workspace():
    import dearpygui.dearpygui as dpg
    from WinUx.ui import StandaloneUiHost, configure_ui_context
    from WinUx.plotdigitizer.ui import PlotDigitizerDialog
    from WinUx.runtime.dpg_callbacks import run_callback_jobs

    class Sink:
        available = True

    dpg.create_context()
    dialog = None
    try:
        host = StandaloneUiHost(dpg)
        configure_ui_context(host)
        dpg.create_viewport(title="Digitizer guided workspace", width=1100, height=780)
        dpg.setup_dearpygui()
        dialog = PlotDigitizerDialog(host, reference_sink=Sink())
        dpg.set_primary_window(dialog.tag, True)
        dpg.show_viewport()

        def pump():
            for _ in range(4):
                run_callback_jobs(dpg.get_callback_queue() or [])
                host.pump()
                dpg.render_dearpygui_frame()
                time.sleep(.005)

        pump()
        yield dialog, dpg, pump
    finally:
        if dialog is not None:
            dialog.destroy()
        dpg.destroy_context()


def test_tooltips_share_listview_theme_delay_and_keep_live_image_details(workspace):
    from DearUIQt.tooltip import TOOLTIP_DELAY, TOOLTIP_WRAP_WIDTH, tooltip_theme
    dialog, dpg, pump = workspace
    tips = [item for item in dpg.get_all_items()
            if dpg.get_item_info(item)["type"].endswith("::mvTooltip")]
    # DPG reports a tooltip's structural parent (the button's container),
    # not its hover anchor. Check all tooltips created by this dialog instead.
    ribbon_count = sum(bool(record.get("tooltip")) for record in dialog.ribbon._buttons.values())
    assert len(tips) >= ribbon_count + 5
    for tip in tips:
        config = dpg.get_item_configuration(tip)
        assert config["delay"] == pytest.approx(TOOLTIP_DELAY)
        assert config["hide_on_activity"]
        assert dpg.get_item_theme(tip) == tooltip_theme()
        texts = [item for item in dpg.get_item_children(tip, 1)
                 if dpg.get_item_info(item)["type"].endswith("::mvText")]
        assert texts
        assert all(dpg.get_item_configuration(item)["wrap"] == TOOLTIP_WRAP_WIDTH for item in texts)
    assert dpg.get_item_parent(dialog._image_details) in tips
    dpg.set_value(dialog._image_details, "Updated image metadata")
    assert dpg.get_value(dialog._image_details) == "Updated image metadata"


def test_history_commands_are_shared_and_refresh_before_deferred_redraw(workspace):
    dialog, dpg, pump = workspace
    original = dialog.engine.active_dataset.name
    assert not dialog._history_actions["undo"].isEnabled()
    dialog.engine.update_dataset(name="Renamed without pumping")
    assert dialog._history_actions["undo"].isEnabled()
    assert dpg.get_item_configuration(dialog.undo_button)["enabled"]
    dialog.ribbon._button_clicked("undo")
    assert dialog.engine.active_dataset.name == original
    assert dialog._history_actions["redo"].isEnabled()
    with patch.object(dpg, "get_focused_item", return_value=0), \
         patch.object(dpg, "is_key_down", side_effect=lambda key: key in (dpg.mvKey_LControl, dpg.mvKey_LShift)):
        dialog._edit_key(None, dpg.mvKey_Z)
    assert dialog.engine.active_dataset.name == "Renamed without pumping"
    assert not dialog._history_actions["redo"].isEnabled()
    commands = list(dialog._history_actions.values())
    dialog.destroy()
    assert all(command._deleted for command in commands)
    assert not dialog._trigger_history_command("undo")
    dialog._engine_changed("state_restored", dialog.engine)  # late queued notification


def test_compact_workspace_and_command_readiness_follow_image_calibration_and_active_data(workspace, tmp_path):
    dialog, dpg, pump = workspace

    def enabled(item):
        return dpg.get_item_configuration(item)["enabled"]

    for removed in ("workflow_button", "workflow_info", "next_step_info", "dataset_summary",
                    "sample_color_info", "export_csv_button", "dataset_visible", "dataset_locked",
                    "duplicate_dataset_button"):
        assert not hasattr(dialog, removed)
    assert not dpg.get_item_configuration(dialog.status)["show"]
    assert not dpg.get_item_configuration(dialog.calibration_hint)["show"]
    assert not dialog.has_footer
    assert dialog.footer is None and dialog.footer_shell is None
    assert not hasattr(dialog, "reference_button")
    for item in (dialog.calibrate_button, dialog.apply_calibration_button, dialog.calibrate_area_button,
                 dialog.find_colors_button, dialog.add_point_button, dialog.ribbon.button_tag("fit"),
                  dialog.delete_dataset_button):
        assert not enabled(item)
    assert not enabled(dialog.ribbon.button_tag("export_csv"))
    row_height = dialog.dataset_list.rowHeight()
    assert dpg.get_item_configuration(dialog.dataset_list.tag)["height"] == 2 * row_height + 2
    with patch.object(dialog, "_file_picker") as picker:
        dialog.ribbon._button_clicked("open_image")
        picker.assert_called_once()

    path = tmp_path / "chart.png"
    Image.new("RGB", (121, 121), "white").save(path)
    dialog._open_image(str(path))
    pump()
    assert dpg.get_value(dialog.project_info) == path.name
    assert "121 x 121" in dpg.get_value(dialog._image_details)
    assert not dpg.get_item_configuration(dialog.status)["show"]
    assert enabled(dialog.calibrate_button)
    assert enabled(dialog.ribbon.button_tag("fit"))
    assert enabled(dialog.add_point_button)
    assert not enabled(dialog.apply_calibration_button)
    dialog._start_calibration()
    assert dialog._pick_mode == "x1"
    assert dpg.get_item_configuration(dialog.calibration_hint)["show"]
    dialog._cancel_pick()
    assert not dpg.get_item_configuration(dialog.calibration_hint)["show"]
    dialog.engine.add_manual_point(60, 60)
    dialog._show_tool("data")
    pump()
    assert dpg.get_item_state(dialog.data_coordinate_info)["visible"]
    assert dialog.result_grid.rows[0][1][1:] == ("60", "60")
    assert not enabled(dialog.ribbon.button_tag("export_csv"))
    for key, px, py, value in (("x1", 10, 110, 0), ("x2", 110, 110, 10),
                               ("y1", 10, 110, 0), ("y2", 10, 10, 100)):
        dialog.engine.set_anchor(key, px, py, value)
    pump()
    assert dialog.result_grid.rows[0][1][1:] == ("5", "50")
    assert enabled(dialog.apply_calibration_button)
    assert enabled(dialog.ribbon.button_tag("export_csv"))
    assert not enabled(dialog.delete_points_button)
    dialog._point_selected("manual:0")
    assert enabled(dialog.delete_points_button)
    dialog.engine.update_dataset(locked=True)
    pump()
    assert not enabled(dialog.delete_points_button)
    assert not enabled(dialog.clear_points_button)
    assert enabled(dialog.ribbon.button_tag("export_csv"))
    dialog.engine.add_dataset("Empty")
    pump()
    dpg.set_value(dialog.export_scope, "Active dataset")
    dialog._refresh_export_controls()
    assert not enabled(dialog.ribbon.button_tag("export_csv"))
    dpg.set_value(dialog.export_scope, "All datasets")
    dialog._refresh_export_controls()
    assert enabled(dialog.ribbon.button_tag("export_csv"))
    dialog.engine.set_plot_rect((10, 10, 110, 110))
    pump()
    assert enabled(dialog.calibrate_area_button)
    assert sum(command["label"] == "Export CSV" for command in dialog.ribbon._buttons.values()) == 1


def test_ribbon_captions_and_commands_fit_their_native_clip_rectangles(workspace):
    from WinUx.ui import RibbonBar, item_rect
    dialog, dpg, pump = workspace
    # Exercise both density presets with the actual shared 14px Segoe UI font.
    window = dpg.add_window(label="Normal ribbon geometry", width=650, height=250, pos=(40, 200))
    normal = RibbonBar(window, quick_access=False, density="normal")
    normal.add_tab("test", "Test")
    # Deliberately narrow: the group must grow to fit its commands.
    normal.add_group("test", "project", "Project", width=72, layout="large")
    normal.add_button("test", "project", "open", "Open Image", lambda: None, image="Open_Folder")
    normal.add_button("test", "project", "save", "Save Project", lambda: None, image="Editor_Save")
    pump()
    assert not hasattr(dialog, "canvas_info")
    assert not hasattr(dialog, "image_bar")
    for key in ("fit", "one_to_one", "box"):
        assert dialog.ribbon._buttons[key]["tab"] == "view"
    panel, frame = item_rect(dialog.canvas_panel), item_rect(dialog.canvas_frame)
    assert frame[1] - panel[1] < 20  # No toolbar-sized gap above the image surface.

    for ribbon in (dialog.ribbon, normal):
        for tab in ribbon._tabs:
            ribbon.set_active_tab(tab)
            for enabled in (False, True):
                for key in ribbon._buttons:
                    ribbon.set_button_enabled(key, enabled)
                pump()
                for group in ribbon._groups.values():
                    if group["tab"] != tab:
                        continue
                    ancestors = (group["tag"], ribbon._tabs[tab]["page"], ribbon.body, ribbon.tag)
                    footer = item_rect(group["footer"])
                    assert footer is not None
                    for ancestor in ancestors:
                        bounds = item_rect(ancestor)
                        assert bounds[1] <= footer[1]
                        assert footer[3] <= bounds[3] - 1, (ribbon.density, group["key"], footer, bounds)
                    for command in ribbon._buttons.values():
                        if command.get("tab") != tab or command.get("group") != group["key"]:
                            continue
                        for item in command["items"]:
                            rect = item_rect(item)
                            for ancestor in (group["controls"], *ancestors):
                                bounds = item_rect(ancestor)
                                assert bounds[0] <= rect[0] and rect[2] <= bounds[2] - 1, (
                                    ribbon.density, enabled, command["key"], rect, bounds)
                                assert bounds[1] <= rect[1] and rect[3] <= bounds[3] - 1, (
                                    ribbon.density, enabled, command["key"], rect, bounds)
                            if command.get("large_tile"):
                                assert dpg.get_item_rect_size(item)[0] == command["width"]
        ribbon.set_minimized(True)
        ribbon.set_minimized(False)
        assert dpg.get_item_configuration(ribbon.tag)["height"] == ribbon._expanded_height
    for _ in range(5):
        dialog.engine.add_dataset()
    pump()
    row_height = dialog.dataset_list.rowHeight()
    assert dpg.get_item_configuration(dialog.dataset_list.tag)["height"] == 5 * row_height + 2


def test_regions_have_uniform_gutters_and_fill_to_the_bottom_after_resize(workspace):
    from WinUx.ui import item_rect
    dialog, dpg, pump = workspace

    def check_geometry():
        content = item_rect(dialog.content)
        panels = [item_rect(item) for item in (dialog.dataset_panel, dialog.canvas_panel, dialog.settings_panel)]
        frame = item_rect(dialog.canvas_frame)
        assert max(rect[1] for rect in panels) - min(rect[1] for rect in panels) <= 1
        assert max(rect[3] for rect in panels) - min(rect[3] for rect in panels) <= 1
        for left, right in zip(panels, panels[1:]):
            assert abs(right[0] - left[2] - dialog.REGION_GAP) <= 2, (left, right)
        for rect in panels:
            assert 0 <= content[3] - rect[3] <= dialog.OUTER_MARGIN + 4
        assert abs(frame[1] - panels[1][1]) <= 1
        assert 0 <= panels[1][3] - frame[3] <= 2
        assert 0 <= panels[1][2] - frame[2] <= 2
        # The controls region starts at its first group, without a duplicate page heading.
        first_page = dialog._tool_pages["axes"]
        first_box = dpg.get_item_children(first_page, 1)[0]
        assert abs(item_rect(first_box)[1] - panels[2][1]) <= 2
        for key, editor in dialog.anchor_value.items():
            value_rect = item_rect(editor)
            pick_rect = item_rect(dialog.anchor_pick_buttons[key])
            assert 4 <= pick_rect[0] - value_rect[2] <= 6
            assert 0 <= panels[2][2] - pick_rect[2] <= 16, (value_rect, pick_rect, panels[2])
        return frame

    before = check_geometry()
    dpg.set_viewport_width(1400)
    dpg.set_viewport_height(960)
    pump()
    pump()
    after = check_geometry()
    assert after[2] - after[0] > before[2] - before[0] + 200
    assert after[3] - after[1] > before[3] - before[1] + 100
    dpg.set_viewport_width(1100)
    dpg.set_viewport_height(780)
    pump()
    pump()
    check_geometry()


def test_command_pairs_fill_the_panel_and_navigation_has_no_obstructing_tooltip(workspace):
    from WinUx.ui import item_rect
    dialog, dpg, pump = workspace
    for children in dpg.get_item_children(dialog.tool_list.tag).values():
        for child in children or []:
            assert "Tooltip" not in dpg.get_item_info(child)["type"]
    for tool, first, second in (
        ("manual", dialog.add_point_button, dialog.edit_points_button),
        ("automatic", dialog.find_colors_button, dialog.extract_button),
    ):
        dialog._show_tool(tool)
        pump()
        bounds, left, right = item_rect(dialog.settings_panel), item_rect(first), item_rect(second)
        assert abs((left[2] - left[0]) - (right[2] - right[0])) <= 1
        assert 4 <= right[0] - left[2] <= 10
        inset = 0 if tool == "manual" else 8
        assert inset <= left[0] - bounds[0] <= inset + 5
        assert inset <= bounds[2] - right[2] <= inset + 5


def test_point_navigation_updates_coordinates_respects_locks_and_preserves_history(workspace, tmp_path):
    from WinUx.plotdigitizer.core import SmartDetectionResult
    dialog, dpg, pump = workspace
    path = tmp_path / "manual.png"
    Image.new("RGB", (201, 121), "white").save(path)
    dialog._open_image(str(path))
    for key, px, py, value in (("x1", 0, 110, 0), ("x2", 200, 110, 20),
                               ("y1", 0, 110, 0), ("y2", 0, 10, 100)):
        dialog.engine.set_anchor(key, px, py, value)
    dialog.engine.apply_smart_detect_result(SmartDetectionResult(
        plot_rect=(0, 10, 200, 110), curve_rgb=(30, 100, 220),
        extracted_pixels=[(20, 90), (80, 60)]))
    dialog.engine.add_manual_point(150, 30)
    dialog._show_tool("manual")
    pump()
    assert dpg.get_item_configuration(dialog.point_editor_container)["show"]
    assert not dpg.get_item_configuration(dialog.point_fields)["show"]
    before = dialog.engine.to_result_dict()
    revision = dialog.engine.revision

    for selected, values in ((('auto', 0), (2, 20)), (('auto', 1), (8, 50)), (('manual', 0), (15, 80))):
        assert dialog._navigate_point(1)
        pump()
        assert dialog._selected_point == selected
        assert dialog.result_grid.currentKey() == '{}:{}'.format(*selected)
        assert (float(dpg.get_value(dialog.point_x)), float(dpg.get_value(dialog.point_y))) == values
    assert dialog.engine.to_result_dict() == before
    assert dialog.engine.revision == revision
    assert not dialog._navigate_point(1)


    assert not dpg.get_item_configuration(dialog.next_point_button)["enabled"]

    dpg.set_value(dialog.coordinate_mode, "Image pixels")
    dialog._refresh_grid()
    pump()
    assert dpg.get_value(dialog.point_x) == "150"
    dpg.set_value(dialog.point_x, "155")
    dpg.set_value(dialog.point_y, "35")
    dialog._apply_point()
    pump()
    assert dialog.engine.point_pixels('manual', 0) == (155, 35)
    dialog._undo()
    pump()
    assert dialog.engine.point_pixels('manual', 0) == (150, 30)
    assert dialog._selected_point is None
    assert not dpg.get_item_configuration(dialog.point_fields)["show"]

    dialog.engine.update_dataset(locked=True)
    pump()
    assert dialog._navigate_point(-1)  # No selection: begin at the last point.
    pump()
    assert dialog._selected_point == ('manual', 0)
    for item in (dialog.point_x, dialog.point_y, dialog.apply_point_button):
        assert not dpg.get_item_configuration(item)["enabled"]
    locked_revision = dialog.engine.revision
    with patch.object(dpg, "get_focused_item", return_value=dialog.point_x):
        dialog._edit_key(None, dpg.mvKey_P)
    assert dialog._selected_point == ('manual', 0)
    dialog._pan = [10000, 10000]
    zoom = dialog._zoom
    with patch.object(dpg, "get_focused_item", return_value=None), \
         patch.object(dpg, "is_key_down", return_value=False):
        dialog._edit_key(None, dpg.mvKey_P)
    pump()
    assert dialog._selected_point == ('auto', 1)
    _, (width, height) = dialog._canvas_rect()
    assert dialog._image_to_canvas(80, 60) == pytest.approx((width / 2, height / 2))
    assert dialog._zoom == zoom
    assert dialog.engine.revision == locked_revision
    dialog.engine.add_dataset("Empty")
    pump()
    assert not dpg.get_item_configuration(dialog.point_editor_container)["show"]
    assert not dialog._navigate_point(1)


def test_reduce_samples_button_updates_grid_csv_and_undo_without_stale_selection(workspace, tmp_path):
    from WinUx.plotdigitizer.core import ExtractionSettings
    dialog, dpg, pump = workspace
    assert dpg.get_item_configuration(dialog.reduce_samples_button)["label"] == "Reduce Samples"
    assert not dpg.get_item_configuration(dialog.reduce_samples_button)["enabled"]
    image = Image.new("RGB", (121, 121), "white")
    ImageDraw.Draw(image).line((10, 100, 110, 20), fill=(220, 30, 50), width=1)
    path = tmp_path / "dense.png"
    image.save(path)
    dialog._open_image(str(path))
    for key, px, py, value in (("x1", 10, 110, 0), ("x2", 110, 110, 10),
                               ("y1", 10, 110, 0), ("y2", 10, 10, 100)):
        dialog.engine.set_anchor(key, px, py, value)
    dialog.engine.set_curve_color((220, 30, 50))
    assert dialog.engine.extract(ExtractionSettings(smoothing=0))
    dialog._show_tool("data")
    pump()
    assert len(dialog.result_grid.rows) == 101
    assert dpg.get_item_configuration(dialog.reduce_samples_button)["enabled"]
    dialog.result_grid.setCurrentKey("auto:50", select=True)
    original = dialog.engine.active_dataset.to_dict()
    dialog._reduce_samples()
    pump()
    assert len(dialog.result_grid.rows) == 2
    assert dialog.engine.active_dataset.extracted_data == [(0, 10), (10, 90)]
    assert dialog._selected_point is None
    assert not dialog.result_grid.selectedKeys()
    assert "101 -> 2" in dpg.get_value(dialog.status)
    assert not dpg.get_item_configuration(dialog.reduce_samples_button)["enabled"]
    dialog._export_csv(str(tmp_path / "reduced.csv"))
    assert len((tmp_path / "reduced.csv").read_text(encoding="utf-8").splitlines()) == 3
    dialog._undo()
    pump()
    assert dialog.engine.active_dataset.to_dict() == original
    assert len(dialog.result_grid.rows) == 101
    dialog._redo()
    pump()
    assert len(dialog.result_grid.rows) == 2
    dialog._undo()
    dialog.engine.update_dataset(locked=True)
    pump()
    assert not dpg.get_item_configuration(dialog.reduce_samples_button)["enabled"]
    dialog._reduce_samples()
    assert len(dialog.engine.active_dataset.extracted_pixels) == 101
    assert "Unlock" in dpg.get_value(dialog.status)


def test_list_padding_series_checkboxes_and_lock_context_menu(workspace, tmp_path):
    from WinUx.ui import item_rect
    dialog, dpg, pump = workspace
    path = tmp_path / "series.png"
    Image.new("RGB", (121, 121), "white").save(path)
    dialog._open_image(str(path))
    dialog.engine.add_dataset()
    dialog.engine.add_manual_point(30, 40)
    dialog.engine.add_dataset()
    dialog.engine.set_active_dataset(0)
    pump()
    assert [dataset.name for dataset in dialog.engine.datasets] == ["Serie-1", "Serie-2", "Serie-3"]
    assert set(dialog.dataset_list.checkboxes) == {0, 1, 2}
    assert dpg.get_y_scroll_max(dialog.dataset_list.tag) == 0
    for row in dialog.tool_list.items.values():
        assert item_rect(row)[0] - item_rect(dialog.tool_list.tag)[0] >= 5
    for key, checkbox in dialog.dataset_list.checkboxes.items():
        checkbox_rect = item_rect(checkbox)
        text_rect = item_rect(dialog.dataset_list.items[key])
        assert checkbox_rect[0] - item_rect(dialog.dataset_list.tag)[0] >= 5
        assert checkbox_rect[2] < text_rect[0]
        assert abs((checkbox_rect[1] + checkbox_rect[3]) / 2 -
                   (text_rect[1] + text_rect[3]) / 2) <= 1

    checkbox = dialog.dataset_list.checkboxes[1]
    config = dpg.get_item_configuration(checkbox)
    config["callback"](checkbox, False, config["user_data"])
    pump()
    assert not dialog.engine.datasets[1].visible
    assert not dpg.get_value(dialog.dataset_list.checkboxes[1])
    assert dialog.engine.active_dataset_index == 0
    assert dialog.dataset_list.currentKey() == 0

    row = dialog.dataset_list.items[1]
    left, top, right, bottom = item_rect(row)
    point = (left + 8, (top + bottom) / 2)
    with patch.object(dpg, "get_mouse_pos", return_value=point), \
         patch.object(dpg, "is_item_hovered", side_effect=lambda item: item == row):
        dialog.dataset_list._context_mouse_down()
    assert dialog.engine.active_dataset_index == 1
    assert dialog.dataset_menu._actions[0]["label"] == "Lock"
    dialog.dataset_menu._row_clicked(user_data="lock")
    pump()
    assert dialog.engine.datasets[1].locked
    assert "[Locked]" in dpg.get_item_configuration(dialog.dataset_list.items[1])["label"]
    assert not dpg.get_item_configuration(dialog.add_point_button)["enabled"]
    assert not dpg.get_item_configuration(dialog.dataset_name)["enabled"]
    assert dpg.get_item_configuration(dialog.dataset_list.checkboxes[1])["enabled"]
    dialog._dataset_context_open(1, point)
    assert dialog.dataset_menu._actions[0]["label"] == "Unlock"
    dialog.dataset_menu._row_clicked(user_data="unlock")
    pump()
    assert not dialog.engine.datasets[1].locked
    assert dpg.get_item_configuration(dialog.add_point_button)["enabled"]
    dialog._undo()
    pump()
    assert dialog.engine.datasets[1].locked
    dialog._redo()
    pump()
    assert not dialog.engine.datasets[1].locked


def test_series_context_and_checkboxes_do_not_mutate_replacement_rows(workspace):
    dialog, dpg, pump = workspace
    dialog.engine.add_dataset()
    dialog.engine.add_dataset()
    pump()
    checkbox = dialog.dataset_list.checkboxes[1]
    old_callback = dpg.get_item_configuration(checkbox)
    dialog._refresh_dataset_list()
    old_callback["callback"](checkbox, False, old_callback["user_data"])
    assert all(dataset.visible for dataset in dialog.engine.datasets)
    # An open menu retains its actual dataset, not a now-reused row index.
    target = dialog.engine.datasets[1]
    dialog._dataset_context_open(1, (30, 300))
    dialog.engine.remove_dataset(1)
    dialog.dataset_menu._row_clicked(user_data="lock")
    pump()
    assert target not in dialog.engine.datasets
    assert all(not dataset.locked for dataset in dialog.engine.datasets)


def test_pdg_restores_image_camera_selection_controls_and_undo_history(workspace, tmp_path):
    from WinUx.plotdigitizer.core import SmartDetectionResult
    dialog, dpg, pump = workspace
    source = tmp_path / "embedded.png"
    Image.new("RGB", (121, 121), (230, 240, 250)).save(source)
    dialog._open_image(str(source))
    for key, px, py, value in (("x1", 10, 110, 0), ("x2", 110, 110, 10),
                               ("y1", 10, 110, 0), ("y2", 10, 10, 100)):
        dialog.engine.set_anchor(key, px, py, value)
    dialog.engine.apply_smart_detect_result(SmartDetectionResult(
        plot_rect=(10, 10, 110, 110), curve_rgb=(220, 30, 50),
        extracted_pixels=[(10 + index, 100 - index) for index in range(21)]))
    dialog.engine.add_dataset()
    dialog.engine.update_dataset(visible=False, locked=True)
    dialog.engine.set_active_dataset(0)
    dialog._show_tool("data")
    pump()
    dpg.set_value(dialog.coordinate_mode, "Image pixels")
    dpg.set_value(dialog.export_scope, "Active dataset")
    dialog._control_wrappers[dialog.export_sort_x].setChecked(True)
    dialog._control_wrappers[dialog.reduction_error].setValue(0.25)
    dialog._refresh_grid()
    dialog.result_grid.setCurrentKey("auto:3", select=True)
    dialog.ribbon.set_active_tab("view")
    dpg.set_value(dialog._disclosures["reduction"], True)
    pump()
    dialog._zoom_at(1.8)
    dialog._pan = [-25, 35]
    dialog._redraw()
    view_before = dialog._capture_project_view()
    data_before = dialog.engine._snapshot()
    history_before = len(dialog.engine._undo_stack)
    pixels_before = dialog.engine.image.tobytes()
    saved = tmp_path / "workspace.pdg"
    dialog._save_project(str(saved))
    assert saved.exists()
    source.unlink()
    replacement = tmp_path / "replacement.png"
    Image.new("RGB", (80, 80), "black").save(replacement)
    dialog._open_image(str(replacement))
    pump()
    dialog._load_project(str(saved))
    pump()
    pump()
    pump()
    assert dialog.engine._snapshot() == data_before
    assert dialog.engine.image.tobytes() == pixels_before
    assert len(dialog.engine._undo_stack) == history_before
    assert dialog._active_tool == "data"
    assert dialog.ribbon.active_tab() == "view"
    assert dialog._selected_point == ("auto", 3)
    assert dialog.result_grid.selectedKeys() == ["auto:3"]
    assert dpg.get_value(dialog.coordinate_mode) == "Image pixels"
    assert dpg.get_value(dialog.export_scope) == "Active dataset"
    assert dpg.get_value(dialog.export_sort_x)
    assert dpg.get_value(dialog.reduction_error) == pytest.approx(0.25)
    assert dpg.get_value(dialog._disclosures["reduction"])
    assert dialog._fit_scale * dialog._zoom == pytest.approx(view_before["scale"])
    assert dialog._zoom == pytest.approx(view_before["zoom"])
    assert dialog._pan == pytest.approx(view_before["pan"])
    assert dpg.get_value(dialog.point_x) == "13"
    assert dpg.get_value(dialog.point_y) == "97"


def test_project_file_actions_default_to_pdg_and_load_legacy_json(workspace):
    dialog, _dpg, _pump = workspace
    with patch.object(dialog, "_file_picker") as picker:
        dialog._choose_save_project()
        assert picker.call_args.kwargs["extensions"] == (".pdg",)
        assert picker.call_args.kwargs["default_filename"].endswith(".pdg")
        dialog._choose_load_project()
        assert picker.call_args.kwargs["extensions"] == (".pdg", ".json")


def test_pdg_preserves_uncommitted_tick_values_palette_and_guided_calibration(workspace, tmp_path):
    dialog, dpg, pump = workspace
    source = tmp_path / "partial.png"
    Image.new("RGB", (121, 121), "white").save(source)
    dialog._open_image(str(source))
    pump()
    dialog.engine.set_curve_color((30, 100, 220))
    dialog._start_calibration()
    dialog._control_wrappers[dialog.anchor_value["x1"]].setText("12.345")
    dialog._control_wrappers[dialog.anchor_value["x2"]].setText("draft tick")
    dialog._palette = [(30, 100, 220), (220, 30, 50)]
    dpg.configure_item(dialog.palette_combo, items=["#1E64DC", "#DC1E32"], show=True)
    dpg.set_value(dialog.palette_combo, "#1E64DC")
    dialog._sample_pixel = (20, 20)
    dpg.set_value(dialog._disclosures["axes"], True)
    saved = tmp_path / "partial.pdg"
    dialog._save_project(str(saved))
    assert saved.exists()
    dialog._cancel_pick()
    dialog._control_wrappers[dialog.anchor_value["x1"]].setText("0")
    dialog._load_project(str(saved))
    pump()
    pump()
    pump()
    assert dialog.engine.calibration.x1 is None
    assert dpg.get_value(dialog.anchor_value["x1"]) == "12.345"
    assert dpg.get_value(dialog.anchor_value["x2"]) == "draft tick"
    assert dialog._pick_mode == "x1"
    assert dialog._calibration_sequence == ["x1", "x2", "y1", "y2"]
    assert dialog._palette == [(30, 100, 220), (220, 30, 50)]
    assert dialog._sample_pixel == [20, 20]
    assert dpg.get_value(dialog.palette_combo) == "#1E64DC"
    assert dpg.get_value(dialog._disclosures["axes"])
