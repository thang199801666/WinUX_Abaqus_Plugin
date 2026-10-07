"""Regression coverage for Job Viewer realtime ODB History Plots."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "WinUx" / "services" / "odb_history_live.py"
SERVER = ROOT / "WinUx" / "server_model.py"
REMOTE_ODB = ROOT / "WinUx" / "services" / "remote_odb.py"
CONTROLLER = ROOT / "WinUx" / "controller.py"
JOB_PLOT_CONTROLLER = ROOT / "WinUx" / "controllers" / "job_plot.py"
JOBS = ROOT / "WinUx" / "components" / "jobs_view.py"
PLOTS = ROOT / "WinUx" / "components" / "job_plots.py"
DOCK = ROOT / "WinUx" / "components" / "dock_widget.py"
DOCK_MANAGER = ROOT / "WinUx" / "components" / "dock_manager.py"
VIEW = ROOT / "WinUx" / "view.py"
EXPLORER = ROOT / "WinUx" / "components" / "explorer_list_view.py"
EXPLORER_POINTER = ROOT / "WinUx" / "components" / "explorer_pointer_capture.py"
EXPLORER_DRAG_DROP = ROOT / "WinUx" / "components" / "explorer_drag_drop.py"
EXPLORER_CONTEXT = ROOT / "WinUx" / "components" / "explorer_context_menu.py"
INTERACTION_GATE = ROOT / "WinUx" / "components" / "interaction_gate.py"
FLOAT_RESIZER = ROOT / "WinUx" / "components" / "floating_window_resizer.py"
SPLITTER_LAYOUT = ROOT / "WinUx" / "ui" / "splitter_layout.py"
PLOT_DOCKING = ROOT / "WinUx" / "ui" / "plot_docking.py"
CONSOLE_DOCKING = ROOT / "WinUx" / "ui" / "console_docking.py"
VIEW_RUNTIME_SOURCE = "\n".join(
    path.read_text(encoding="utf-8")
    for path in (VIEW, SPLITTER_LAYOUT, PLOT_DOCKING, CONSOLE_DOCKING)
)

SPEC = importlib.util.spec_from_file_location("winux_odb_history_live", SERVICE)
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


class LiveHistoryServiceTests(unittest.TestCase):
    def test_remote_helper_is_python2_compatible_and_updates_live_odb(self):
        script = live.build_remote_odb_history_live_script()
        self.assertIn("from odbAccess import openOdb", script)
        self.assertIn('getattr(odb, "update", None)', script)
        self.assertIn("select.select([sys.stdin]", script)
        self.assertIn('command.get("cmd") == "select"', script)
        self.assertIn('"type": "catalog"', script)
        self.assertIn('"type": "frame"', script)
        self.assertNotIn('f"', script)
        compile(script, "remote_live_odb.py", "exec")

    def test_default_selection_is_allke_and_allie_only(self):
        rows = [
            {"id": "A", "output": "ALLAE"},
            {"id": "B", "output": "ALLKE"},
            {"id": "C", "output": "allie"},
            {"id": "D", "output": "RF2"},
        ]
        self.assertEqual(live.default_history_ids(rows), ["B", "C"])

    def test_delta_merge_appends_and_reset_replaces(self):
        existing = [[0.0, 1.0], [1.0, 2.0]]
        merged = live.merge_series_delta(
            existing, {"reset": False, "points": [[2, 3], [3, 4]]})
        self.assertEqual(merged, [
            [0.0, 1.0], [1.0, 2.0], [2.0, 3.0], [3.0, 4.0]])
        replaced = live.merge_series_delta(
            merged, {"reset": True, "points": [[10, 20]]})
        self.assertEqual(replaced, [[10.0, 20.0]])

    def test_live_message_parser_ignores_abaqus_banner_lines(self):
        self.assertIsNone(live.parse_live_message("Abaqus JOB monitor banner"))
        parsed = live.parse_live_message(
            live.LIVE_PREFIX + '{"type":"status","state":"live"}')
        self.assertEqual(parsed["state"], "live")

    def test_remote_delta_emits_only_new_points_after_first_frame(self):
        class Output:
            def __init__(self):
                self.description = "Kinetic energy: ALLKE for Whole Model"
                self.data = [(0.0, 1.0), (1.0, 2.0)]

        output = Output()

        class Region:
            description = "Whole Model"
            historyOutputs = {"ALLKE": output}

        class Step:
            historyRegions = {"Assembly ASSEMBLY": Region()}

        class Odb:
            steps = {"Step-1": Step()}

        fake = types.ModuleType("odbAccess")
        fake.openOdb = lambda path, readOnly=True: Odb()
        old = sys.modules.get("odbAccess")
        sys.modules["odbAccess"] = fake
        try:
            ns = {"__name__": "winux_remote_test"}
            exec(compile(live.ODB_HISTORY_LIVE_SCRIPT, "remote.py", "exec"), ns)
            catalog = ns["_catalog"](Odb(), "/tmp/job.odb")
            item = dict(catalog["historyOutputs"][0])
            counts = {}
            first = ns["_selected_series"](Odb(), [item], counts)
            self.assertTrue(first[0]["reset"])
            self.assertEqual(first[0]["points"], [[0.0, 1.0], [1.0, 2.0]])
            output.data.append((2.0, 3.0))
            second = ns["_selected_series"](Odb(), [item], counts)
            self.assertFalse(second[0]["reset"])
            self.assertEqual(second[0]["points"], [[2.0, 3.0]])
        finally:
            if old is None:
                sys.modules.pop("odbAccess", None)
            else:
                sys.modules["odbAccess"] = old


class JobPlotsArchitectureTests(unittest.TestCase):
    def test_job_viewer_context_menu_exposes_checkable_plots(self):
        source = JOBS.read_text(encoding="utf-8")
        self.assertIn('"label": "Plots"', source)
        self.assertIn('"action": "job_plots"', source)
        self.assertIn('"checkable": True', source)
        self.assertIn("set_plots_open_job", source)
        self.assertIn("set_context_menu_item_checked", source)


    def test_explorer_context_menu_supports_runtime_checkmarks(self):
        source = EXPLORER_CONTEXT.read_text(encoding="utf-8")
        self.assertIn('item.setdefault("checkable", False)', source)
        self.assertIn('item.setdefault("checked", False)', source)
        self.assertIn("def set_context_menu_item_checked", source)
        self.assertIn("_render_context_menu_check_slot", source)

    def test_plot_panel_uses_dearpygui_plot_and_checkbox_catalog(self):
        source = PLOTS.read_text(encoding="utf-8")
        self.assertIn("class JobPlotsWindow", source)
        self.assertIn("DockWidget(", source)
        self.assertNotIn("with dpg.window(", source)
        self.assertIn("dpg.plot(", source)
        self.assertIn("dpg.add_plot_axis", source)
        self.assertIn("dpg.add_line_series", source)
        self.assertIn("dpg.add_checkbox", source)
        self.assertIn("default_history_ids", source)
        self.assertNotIn('label="Auto fit"', source)
        self.assertIn("PANEL_GAP = 8", source)
        self.assertIn("HISTORY_ROW_GAP = 3", source)
        self.assertIn("OUTER_MARGIN = 6", source)
        self.assertIn('dpg.mvPlotCol_PlotBg', source)
        self.assertIn("panel_surface_theme(", source)
        self.assertIn("checkbox_theme(dpg, checked=False)", source)
        self.assertIn("checkbox_theme(dpg, checked=True)", source)
        self.assertIn("self.toolbar = dpg.add_child_window", source)

    def test_plot_layout_avoids_unsupported_separator_configure_item(self):
        source = PLOTS.read_text(encoding="utf-8")
        self.assertIn("self.header_separator = dpg.add_drawlist", source)
        self.assertIn("def _safe_configure", source)
        self.assertNotIn("dpg.configure_item(self.header_separator", source)

    def test_plot_light_canvas_has_explicit_readable_text_and_bordered_dynamic_checkboxes(self):
        source = PLOTS.read_text(encoding="utf-8")
        self.assertIn("dpg.mvPlotCol_TitleText", source)
        self.assertIn("dpg.mvPlotCol_LegendText", source)
        self.assertIn("dpg.mvPlotCol_InlayText", source)
        self.assertIn("dpg.mvPlotCol_PlotBg, (255, 255, 255, 255)", source)
        self.assertIn("checkbox_theme(dpg, checked=False)", source)
        self.assertIn("checkbox_theme(dpg, checked=True)", source)
        style = (ROOT / "WinUx" / "widgets" / "imgui_qt_style.py").read_text(encoding="utf-8")
        self.assertIn("def checkbox_theme", style)
        self.assertIn("mvStyleVar_FrameBorderSize, 1", style)
        rebuild = source[source.index("def _rebuild_history_list"):source.index("def _checkbox_changed")]
        self.assertIn("self._checkbox_theme_on if item_id in self.selected_ids", rebuild)
        self.assertIn("else self._checkbox_theme_off", rebuild)

    def test_server_has_persistent_live_monitor_on_shared_transport(self):
        source = REMOTE_ODB.read_text(encoding="utf-8")
        facade = SERVER.read_text(encoding="utf-8")
        self.assertIn("RemoteODBMixin", facade)
        self.assertIn("def stream_odb_history", source)
        self.assertIn("with self._auxiliary_session()", source)
        self.assertIn("self._open_transport_session(transport)", source)
        self.assertIn("channel.exec_command(command)", source)
        self.assertIn("channel.sendall", source)
        self.assertIn("build_remote_odb_history_live_script", source)

    def test_controller_waits_for_odb_then_streams_realtime(self):
        facade = CONTROLLER.read_text(encoding="utf-8")
        source = JOB_PLOT_CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("def _job_plot_watch_loop", facade)
        self.assertIn("return self._job_plots.watch_loop", facade)
        self.assertIn("Waiting for job ODB to appear", source)
        self.assertIn("self.server.find_job_output_file", source)
        self.assertIn("self.server.stream_odb_history", source)
        self.assertIn("AbaqusVersionPreferences().ordered_commands()", source)
        self.assertIn('if action == "job_plots"', (ROOT / "WinUx" / "controllers" / "job_actions.py").read_text(encoding="utf-8"))
        self.assertIn("threading.Thread(", source)

    def test_view_supports_qt_dock_areas_and_floating_plot_panel(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("PLOT_DOCK_DEFAULT_RATIO = 0.50", source)
        self.assertIn('PLOT_DOCK_AREAS = ("left", "right", "top", "bottom")', source)
        self.assertIn("self.plot_region = dpg.add_child_window", source)
        self.assertIn("self.job_plot_separator", source)
        self.assertIn("self.job_plot_separator_hitbox", source)
        self.assertIn("def _plot_split_widths", source)
        self.assertIn("def _plot_split_heights", source)
        self.assertIn("def _drag_job_plot_splitter", source)
        self.assertIn("mvMouseCursor_ResizeEW", source)
        self.assertIn("mvMouseCursor_ResizeNS", source)
        self.assertIn('if area == "left"', source)
        self.assertIn('if area == "top"', source)
        self.assertIn("def show_job_plots", source)
        self.assertIn("self.plot_region, key", source)
        self.assertIn("def undock_job_plots", source)
        self.assertIn("def dock_job_plots", source)
        self.assertIn("dpg.move_item(window.root", source)
        self.assertIn("on_close=floating_closed", source)
        self.assertIn("def get_job_plots", source)
        self.assertIn("def close_job_plots", source)
        self.assertIn("def _update_floating_plot_docking", source)
        self.assertIn("self._dock_drop_preview = DockDropPreview()", source)
        self.assertIn("def _set_plot_dock_preview", source)
        self.assertIn("def _plot_dock_target_at_pointer", source)
        self.assertIn("self._plot_splitter_hover_theme", source)

    def test_each_dock_area_remembers_its_own_split_ratio(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("self._plot_split_ratios = {", source)
        self.assertIn("def _plot_ratio_for_area", source)
        self.assertIn("def _set_plot_ratio_for_area", source)
        self.assertIn("available * self._plot_ratio_for_area(area)", source)
        self.assertIn("plot_width = max(1, available - job_width)", source)
        self.assertIn("plot_height = max(1, available - job_height)", source)

    def test_plot_component_exposes_qt_like_float_close_and_drag_contract(self):
        source = PLOTS.read_text(encoding="utf-8")
        dock = DOCK.read_text(encoding="utf-8")
        self.assertIn("DockWidget(", source)
        self.assertIn("self.drag_handle = self.dock.drag_handle", source)
        self.assertIn("add_mouse_drag_handler", source)
        self.assertIn("_on_header_drag", source)
        self.assertIn("on_dock_change", source)
        self.assertIn("class DockWidget", dock)
        self.assertIn("self.float_button = dpg.add_button", dock)
        self.assertIn("self.close_button = dpg.add_button", dock)
        self.assertIn("self.title_overlay = dpg.add_drawlist", dock)
        self.assertIn("self._float_back = dpg.draw_rectangle", dock)
        self.assertIn("self._close_line_a = dpg.draw_line", dock)
        self.assertIn("self.title_bar = dpg.add_child_window", dock)
        self.assertIn("FRAME = 1", dock)
        self.assertIn("TITLE_HEIGHT = 20", dock)
        self.assertIn("def set_floating", dock)

    def test_floating_titlebar_double_click_restores_previous_dock(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("def _left_mouse_double_clicked", source)
        self.assertIn("def _floating_plot_titlebar_hit", source)
        self.assertIn("self.after(0, self.dock_job_plots, key)", source)
        self.assertIn("no_collapse=True", source)

    def test_dock_exposes_qdockwidget_feature_contract_and_title_menu(self):
        dock = DOCK.read_text(encoding="utf-8")
        self.assertIn("DockWidgetClosable = 0x01", dock)
        self.assertIn("DockWidgetMovable = 0x02", dock)
        self.assertIn("DockWidgetFloatable = 0x04", dock)
        self.assertIn("def set_features", dock)
        self.assertIn("def set_feature_enabled", dock)
        self.assertIn("def _show_title_menu", dock)
        self.assertIn('"label": "Dock" if self.floating else "Float"', dock)
        self.assertIn('"id": "close", "label": "Close"', dock)
        self.assertIn("def _elide_title", dock)

    def test_dock_exposes_qmainwindow_style_allowed_dock_areas(self):
        dock = DOCK.read_text(encoding="utf-8")
        plots = PLOTS.read_text(encoding="utf-8")
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("LeftDockWidgetArea = 0x01", dock)
        self.assertIn("RightDockWidgetArea = 0x02", dock)
        self.assertIn("TopDockWidgetArea = 0x04", dock)
        self.assertIn("BottomDockWidgetArea = 0x08", dock)
        self.assertIn("AllDockWidgetAreas", dock)
        self.assertIn("def set_allowed_areas", dock)
        self.assertIn("def set_dock_area", dock)
        self.assertIn('for area_name in ("left", "right", "top", "bottom")', dock)
        self.assertIn('"checkable": True', dock)
        self.assertIn('"label": "Dock {}".format(area_name.title())', dock)
        self.assertIn("on_dock_area_change", plots)
        self.assertIn("def _job_plot_dock_area_change", source)
        self.assertIn("dock_area=self._plot_dock_area", source)

    def test_floating_drag_preview_selects_nearest_qt_dock_area(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("def _plot_dock_target_at_pointer", source)
        self.assertIn('"left": abs(mx - x0)', source)
        self.assertIn('"bottom": abs(my - (y0 + height))', source)
        self.assertIn("self.DOCK_SNAP_DISTANCE", source)
        self.assertIn("def _plot_dock_preview_geometry", source)
        self.assertIn("target_area = self._plot_dock_target_at_pointer()", source)
        self.assertIn("self.after(0, self.dock_job_plots, key, target_area)", source)


    def test_dock_preview_is_viewport_front_and_uses_snap_proximity(self):
        source = VIEW_RUNTIME_SOURCE
        dock = DOCK.read_text(encoding="utf-8")
        self.assertIn("class DockDropPreview", dock)
        self.assertIn("add_viewport_drawlist(front=True", dock)
        self.assertIn("DOCK_SNAP_DISTANCE = 56", source)
        self.assertIn("def _dock_pointer_candidates", source)
        self.assertIn("def _point_near_rect", source)
        self.assertIn("self._left_mouse_pressed()", source)

    def test_qt_like_tearoff_preserves_grab_anchor_and_float_geometry(self):
        plots = PLOTS.read_text(encoding="utf-8")
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("drag_anchor", plots)
        self.assertIn("get_item_rect_min(self.drag_handle)", plots)
        self.assertIn("self._plot_float_geometries = {}", source)
        self.assertIn("def _remember_plot_float_geometry", source)
        self.assertIn("is_drag_tearoff", source)
        self.assertIn("float(pointer_pos[0]) - anchor_x", source)
        self.assertIn("saved_geometry", source)

    def test_escape_cancels_active_floating_dock_drag(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("def _escape_key_pressed", source)
        self.assertIn("escape_pressed = self._escape_key_pressed()", source)
        self.assertIn("escape_pressed and key in self._plot_float_dragging", source)

    def test_splitter_hit_targets_are_larger_than_visible_dividers(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("SPLITTER_SIZE = 1", source)
        self.assertIn("SPLITTER_HIT_PADDING = 10", source)
        self.assertIn("HORIZONTAL_SPLITTER_HIT_PADDING = 18", source)
        self.assertIn("FILE_JOB_SPLITTER_GUTTER_SIZE = 9", source)
        self.assertIn("FILE_PANEL_SPLITTER_GUTTER_SIZE = 9", source)
        self.assertIn("CONSOLE_DOCK_SPLITTER_GUTTER_SIZE = 9", source)
        # Plot splitters still use enlarged invisible halos; the three primary
        # workspace splitters now use explicit layout gutters instead.
        self.assertGreaterEqual(source.count("2 * self.SPLITTER_HIT_PADDING"), 1)

    def test_file_job_splitter_has_dedicated_non_overlapping_gutter(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("FILE_JOB_SPLITTER_GUTTER_SIZE = 9", source)
        self.assertIn("pos=(0, top_height), width=safe_width", source)
        self.assertIn("height=self.FILE_JOB_SPLITTER_GUTTER_SIZE", source)
        self.assertIn("bottom_y = top_height + self.FILE_JOB_SPLITTER_GUTTER_SIZE", source)
        self.assertIn("dpg.get_item_pos(self.horizontal_splitter_hitbox)[1]", source)
        # The File/Job gutter must not borrow the generic 18px halo from the
        # Job Viewer header anymore.
        layout_start = source.index("splitter_line_y = (", source.index("def _apply_split_layout"))
        layout_end = source.index("file_gutter = self.FILE_PANEL_SPLITTER_GUTTER_SIZE", layout_start)
        layout = source[layout_start:layout_end]
        self.assertNotIn("HORIZONTAL_SPLITTER_HIT_PADDING", layout)

    def test_local_server_and_console_use_real_splitter_gutters(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("FILE_PANEL_SPLITTER_GUTTER_SIZE = 9", source)
        self.assertIn("CONSOLE_DOCK_SPLITTER_GUTTER_SIZE = 9", source)
        self.assertIn("self.file_panel_separator_hitbox", source)
        self.assertIn("width=file_gutter, height=file_height", source)
        self.assertIn("pos=(0, console_gutter_y)", source)
        self.assertIn("height=self.CONSOLE_DOCK_SPLITTER_GUTTER_SIZE", source)
        # Local/Server must no longer use a native resizable table divider.
        creation = source[source.index("self.top_region = dpg.add_child_window"):source.index("# Status text is owned", source.index("self.top_region = dpg.add_child_window"))]
        self.assertNotIn("resizable=True", creation)
        self.assertIn("self.file_panels_table = dpg.add_group", creation)

    def test_main_splitter_acquisition_uses_real_hitbox_only(self):
        source = VIEW_RUNTIME_SOURCE
        begin = source[source.index("def _begin_horizontal_splitter_drag"):source.index("def _end_horizontal_splitter_drag")]
        poll = source[source.index("def _update_horizontal_splitter_input"):source.index("def _rename_is_active")]
        self.assertIn("self._horizontal_splitter_native_hovered(", begin)
        self.assertIn("ignore_pointer_capture=force_new_press", begin)
        self.assertIn("acquire_pointer_input(owner)", begin)
        self.assertNotIn("_horizontal_splitter_hit_point()", begin)
        self.assertNotIn("_horizontal_splitter_hit_test()", poll)

    def test_splitter_press_cancels_pending_explorer_drag_state(self):
        source = VIEW_RUNTIME_SOURCE
        explorer = EXPLORER.read_text(encoding="utf-8")
        pointer = EXPLORER_POINTER.read_text(encoding="utf-8")
        drag_drop = EXPLORER_DRAG_DROP.read_text(encoding="utf-8")
        pre_start = source.index("def _pre_dispatch_splitter_input")
        pre_end = source.index("def _horizontal_splitter_native_hovered", pre_start)
        pre = source[pre_start:pre_end]
        self.assertIn("force_new_press=True", pre)
        self.assertIn("def _cancel_explorer_gestures_for_splitter", source)
        self.assertGreaterEqual(
            source.count("self._cancel_explorer_gestures_for_splitter()"), 3)
        self.assertIn("def cancel_pointer_gesture", pointer)
        self.assertIn("self._finish_item_drag(perform_drop=False)", pointer)
        self.assertIn("self._drag_origin_on_item = False", pointer)
        self.assertIn("self._pending_click_index = None", pointer)
        self.assertIn("self._release_pointer_gesture()", pointer)

    def test_all_splitters_capture_before_explorer_callbacks(self):
        source = VIEW_RUNTIME_SOURCE
        update = source[source.index("def update(self):"):source.index("def _update_floating_plot_resize_interaction")]
        self.assertLess(update.index("self._pre_dispatch_splitter_input()"),
                        update.index("self._drain_dpg_callbacks()"))
        self.assertIn("self._file_panel_splitter_owner = object()", source)
        self.assertIn("self._horizontal_splitter_owner = object()", source)
        self.assertIn("self._plot_splitter_owner = object()", source)
        self.assertIn("def _file_panel_splitter_hit_test", source)
        self.assertIn("def _begin_file_panel_splitter_drag", source)
        self.assertIn("acquire_pointer_input(owner)", source)
        self.assertIn("release_pointer_input(self._file_panel_splitter_owner)", source)

    def test_dock_drag_exclusively_owns_pointer_input(self):
        plots = PLOTS.read_text(encoding="utf-8")
        dock = DOCK.read_text(encoding="utf-8")
        explorer_root = EXPLORER.parent
        explorer = "\n".join(
            (explorer_root / name).read_text(encoding="utf-8")
            for name in (
                "explorer_list_view.py",
                "explorer_pointer_dispatch.py",
                "explorer_rendering.py",
                "explorer_rubber_band.py",
            )
        )
        gate = INTERACTION_GATE.read_text(encoding="utf-8")
        self.assertIn("register_pointer_protected_item(self.drag_handle)", dock)
        self.assertIn("self.begin_pointer_capture()", plots)
        self.assertIn("self.end_pointer_capture()", plots)
        self.assertIn("def pointer_input_is_blocked", gate)
        self.assertIn("if pointer_input_is_blocked(self):", explorer)
        self.assertIn("self._hide_rubber_rect()", explorer)
        self.assertIn("register_pointer_protected_item(tag)", source := VIEW_RUNTIME_SOURCE)
        self.assertIn("unregister_pointer_protected_item(tag)", source)


    def test_v1520_has_reusable_qmainwindow_like_dock_manager(self):
        manager = DOCK_MANAGER.read_text(encoding="utf-8")
        components = (ROOT / "WinUx" / "components" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("class DockManager", manager)
        self.assertIn("def add_dock_widget", manager)
        self.assertIn("def remove_dock_widget", manager)
        self.assertIn("def tabify_dock_widget", manager)
        self.assertIn("def raise_dock_widget", manager)
        self.assertIn("def set_dock_area", manager)
        self.assertIn("def set_floating", manager)
        self.assertIn("def save_state", manager)
        self.assertIn("def restore_state", manager)
        self.assertIn("self.tab_strip = dpg.add_child_window", manager)
        self.assertIn('tab_position="bottom"', VIEW_RUNTIME_SOURCE)
        self.assertIn('"DockManager": (".dock_manager", "DockManager")', components)

    def test_v1539_job_plots_use_single_job_without_tabification(self):
        source = VIEW_RUNTIME_SOURCE
        jobs = JOBS.read_text(encoding="utf-8")
        self.assertIn("self.plot_dock_manager = DockManager(", source)
        self.assertIn("manager.add_dock_widget(", source)
        self.assertNotIn("manager.tabify_dock_widget", source)
        self.assertIn("for old_key, old_window in list(self.job_plot_windows.items()):", source)
        self.assertIn("old_window.close(notify=True)", source)
        self.assertIn("the Plot site never exposes a tab bar", source)
        self.assertIn("self._plots_open_job_ids = {key}", jobs)
        self.assertIn("Synchronize the single Plot checkmark", jobs)

    def test_v1520_floating_one_tab_keeps_remaining_docked_group_open(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("manager.set_floating(key, True)", source)
        self.assertIn("manager.has_docked() if manager is not None else False", source)
        self.assertIn("manager.set_floating(key, False)", source)
        self.assertIn("manager.set_dock_area(key, area, group=True)", source)

    def test_v1521_qtabbar_drag_reorder_and_tearoff_contract(self):
        manager = DOCK_MANAGER.read_text(encoding="utf-8")
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("TAB_DRAG_START_DISTANCE", manager)
        self.assertIn("TAB_TEAROFF_DISTANCE", manager)
        self.assertIn("def reorder_dock_widget", manager)
        self.assertIn("move_tab = reorder_dock_widget", manager)
        self.assertIn("def update_interaction", manager)
        self.assertIn("acquire_pointer_input(self._tab_drag_owner)", manager)
        self.assertIn("on_tab_tearoff", manager)
        self.assertIn("self._tab_insert_marker = dpg.draw_line", manager)
        self.assertIn("on_tab_tearoff=self._job_plot_tab_tearoff", source)
        self.assertIn("def _job_plot_tab_tearoff", source)
        self.assertIn("dock_manager.update_interaction()", source)

    def test_v1521_tab_tearoff_keeps_gesture_continuous_and_supports_center_tabify(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("self._plot_synthetic_float_drag = {}", source)
        self.assertIn("Native window dragging cannot inherit that press", source)
        self.assertIn('return "tabify"', source)
        self.assertIn('str(area or "").strip().lower() == "tabify"', source)
        self.assertIn("tabify_target", source)

    def test_v1524_plot_monitor_auto_selects_odb_compatible_abaqus_release(self):
        server = REMOTE_ODB.read_text(encoding="utf-8")
        facade = SERVER.read_text(encoding="utf-8")
        controller = JOB_PLOT_CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("RemoteODBMixin", facade)
        self.assertIn("def _resolve_abaqus_for_odb_on", server)
        self.assertIn("__WINUX_ODB_RELEASE_OK__", server)
        self.assertIn('range(2026, 2017, -1)', facade)
        self.assertIn('"abaqus"', facade)
        self.assertIn('"abaqusCommand": executable', server)
        self.assertIn("Finding compatible Abaqus release", controller)

    def test_controller_toggles_plots_checked_state(self):
        facade = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("return self._job_actions_controller().job_command(action)", facade)
        source = (ROOT / "WinUx" / "controllers" / "job_actions.py").read_text(encoding="utf-8")
        self.assertIn("self.view.get_job_plots(job_id) is not None", source)
        self.assertIn("self.view.close_job_plots", source)
        self.assertIn("self.app._open_job_plots", source)


    def test_checkable_menu_icon_uses_supported_draw_image_tint_keyword(self):
        source = EXPLORER_CONTEXT.read_text(encoding="utf-8")
        self.assertIn("color=tint", source)
        self.assertNotIn("tint_color=tint", source)

    def test_v1523_floating_dock_uses_windows11_rounded_chrome_without_grip(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("dpg.mvStyleVar_WindowRounding, 1", source)
        self.assertIn("dpg.mvThemeCol_ResizeGrip, (0, 0, 0, 0)", source)
        self.assertIn("no_resize=True", source)
        self.assertIn("FloatingWindowResizer(", source)
        self.assertIn("_apply_floating_plot_resize_cursor", source)

    def test_v1523_floating_resizer_supports_all_four_corners_and_pointer_capture(self):
        source = FLOAT_RESIZER.read_text(encoding="utf-8")
        self.assertIn('"nw": "nwse"', source)
        self.assertIn('"ne": "nesw"', source)
        self.assertIn('"sw": "nesw"', source)
        self.assertIn('"se": "nwse"', source)
        self.assertIn("acquire_pointer_input(self)", source)
        self.assertIn("release_pointer_input(self)", source)
        self.assertIn("self.min_width", source)
        self.assertIn("self.min_height", source)

    def test_local_server_splitter_starts_centered_until_user_moves_it(self):
        source = VIEW_RUNTIME_SOURCE
        self.assertIn("self._file_panel_splitter_user_adjusted = False", source)
        self.assertIn("desired_left = (safe_width - file_gutter) * 0.5", source)
        self.assertIn("if not self._file_panel_splitter_user_adjusted:", source)
        self.assertIn("self._file_panel_splitter_user_adjusted = True", source)



if __name__ == "__main__":
    unittest.main()
