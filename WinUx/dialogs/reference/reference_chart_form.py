"""Manage persistent comparison curves in an isolated DPG dialog."""
from __future__ import annotations

import copy

from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.backends import dpg
from DearUIQt.core import Qt, QGlobalInputBinding, QItemInputBinding
from DearUIQt.gui import QClipboard
from DearUIQt.widgets import QFrame, QLabel, QSpacer, QPushButton, QPlotWidget, QPlotAxis
from DearUIQt.layouts import QGridLayout, QSplitter
from DearUIQt.themes import compact_layout_surface_theme
from DearUIQt.modelview import QListWidget, QListWidgetItem
from ...ui.components.reference_data_table import ReferenceDataTable
from DearUIQt.widgets import QMenu
from ...ui.components.toolbar import ResourceTextures
from .formula_catalog import FORMULA_FUNCTIONS, FORMULA_LABELS, DEFAULT_FORMULA
from .preview import ReferencePreviewMixin
from .formula_authoring import ReferenceFormulaMixin
from .series_library import ReferenceSeriesLibraryMixin




def _draft_reference_series(series):
    """Create an editable library draft without cloning large XY arrays.

    Reference points are validated immutable-by-convention while a dialog
    session is open. The editor uses a sparse copy-on-write worksheet, so only
    the series metadata needs a private copy here.
    """
    result = []
    for raw in list(series or []):
        if not isinstance(raw, dict):
            result.append(copy.deepcopy(raw))
            continue
        item = dict(raw)
        # Preserve the exact points object so begin_session + worksheet binding
        # remain O(number of series + visible rows), not O(total points).
        item["points"] = raw.get("points") or []
        result.append(item)
    return result


def _reference_series_signature(series):
    """Cheap identity signature that never compares every XY point."""
    signature = []
    for item in list(series or []):
        if not isinstance(item, dict):
            signature.append((id(item),))
            continue
        points = item.get("points") or []
        signature.append((
            str(item.get("id") or ""),
            str(item.get("name") or ""),
            bool(item.get("enabled", True)),
            str(item.get("kind") or ""),
            str(item.get("formula") or ""),
            len(points),
            id(points),
        ))
    return tuple(signature)


# Regex workbench lives in its own subsystem.  Re-export its historical helper
# surface here because older plugins/tests import these names from
# ``WinUx.dialogs.reference_chart_form``.
from .regex_tester import *  # noqa: F401,F403



class ReferenceChartDialog(
        ReferencePreviewMixin, ReferenceFormulaMixin, ReferenceSeriesLibraryMixin, QtDialog):
    """Reference-series library with two explicit authoring workflows.

    XY Data stores pasted/manual points. Formula stores a persistent regex rule
    resolved against each Plot's History Output catalog at runtime.
    """

    REUSABLE_HOST = True
    XY_MIN_WIDTH = 980
    FORMULA_MIN_WIDTH = 980
    MIN_HEIGHT = 610
    DEFAULT_WIDTH = 1180
    DEFAULT_HEIGHT = 720
    # The Series library and XY worksheet are compact authoring controls.
    # Preview/Plots is the elastic workspace: host resize should be absorbed by
    # the plot instead of proportionally growing all three panes.
    LIBRARY_WIDTH = 150
    EDITOR_DEFAULT_WIDTH = 390
    EDITOR_MIN_WIDTH = 330
    PREVIEW_MIN_WIDTH = 360
    ROW_HEIGHT = 0  # Natural table-row height; only the editor body expands.
    SECTION_GAP = 6
    REDUCTION_PRESETS = (
        ("Exact (0% error)", 0.0),
        ("Ultra (0.005%)", 0.00005),
        ("High fidelity (0.01%)", 0.0001),
        ("Balanced (0.05%)", 0.0005),
    )
    DEFAULT_REDUCTION_PRESET = "High fidelity (0.01%)"

    def __init__(self, view, series, on_result, history_outputs=None):
        self.on_result = on_result
        self._finished = False
        self._series = _draft_reference_series(series)
        self._source_signature = _reference_series_signature(series)
        self._source_revision = None
        self._editing_id = None
        self._editor_dirty = False
        self._selection_guard = False
        self._selected_name = ""
        self._series_selectables = {}
        self._rename_name = None
        self._rename_editor = None
        self._rename_editor_control = None
        self._rename_outside_armed = False
        self._history_outputs = list(history_outputs or [])
        self._preview_history_provider = None
        self._preview_series = []
        self._formula_check_generation = 0
        self._formula_insert_generation = 0
        self._pending_formula_insertion = None
        self._formula_dialog = None
        self._regex_tester_dialog = None
        self._formula_mode = False
        self._reference_type_guard = False
        self._delete_in_progress = False
        self._delete_generation = 0
        # Sample reduction is always measured against the unreduced worksheet
        # snapshot captured at the first reduction pass.  Re-running a stronger
        # preset therefore cannot accumulate geometric drift from earlier
        # simplifications.
        self._reduction_source_points = None
        self._reduction_applied_preset = None
        self._reduction_effective_tolerance = None
        self._reduction_pass_count = 0
        # Keep the worksheet near a useful fixed width while Preview/Plots
        # absorbs dialog resize. A user drag updates this preferred width.
        self._editor_preferred_width = self.EDITOR_DEFAULT_WIDTH
        self._pane_geometry_syncing = False

        # A compact library sits beside one authoring workspace. Metadata spans
        # the workspace; the worksheet and preview share additional width.
        super().__init__(view, "Reference Chart", self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT,
                         resizable=True)
        self.preferred_size = (self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setMinimumSize(self.XY_MIN_WIDTH, self.MIN_HEIGHT)
        self._workspace_grid = self.own_widget(QGridLayout(
            2, column_widths=(self.LIBRARY_WIDTH, None), parent=self.contentWidget(),
            after=self.view.after, height=-1, vertical_dividers=True, resizable=True))
        self._chart_layout_theme = compact_layout_surface_theme(
            padding=(0, 0), spacing=(self.SECTION_GAP, self.SECTION_GAP),
            inner_spacing=(4, 4), cell_padding=(0, 0),
            tag='winux.reference_chart.layout', cache=True)

        self._library_panel_widget = self.own_widget(QFrame(
            parent=self._workspace_grid.cell(0, 0), width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self.library_panel = self._library_panel_widget.tag
        self._library_panel_widget.setTheme(self._chart_layout_theme)
        QLabel("Series", parent=self._library_panel_widget)
        self._library_header = self.own_widget(QGridLayout(
            2, column_widths=(None, None), parent=self._library_panel_widget,
            after=self.view.after, height=self.ROW_HEIGHT))
        self.new_series_button = self.action(
            "New", self._new_series, role="secondary",
            parent=self._library_header.cell(0, 0).tag, width=-1)
        self.delete_series_button = self.action(
            "Delete", self._remove_selected, role="secondary",
            parent=self._library_header.cell(0, 1).tag, width=-1)
        # Reference type belongs to the Series controls.  Keeping it here makes
        # the left library the single place for create/delete/type operations
        # and leaves the authoring workspace completely available to XY/Plot.
        self._reference_type_row = self.own_widget(QGridLayout(
            2, column_widths=(42, None), parent=self._library_panel_widget,
            after=self.view.after, height=self.ROW_HEIGHT))
        QLabel("Type", parent=self._reference_type_row.cell(0, 0))
        self.reference_type_combo = self.combo(
            ("XY Data", "Formula"), parent=self._reference_type_row.cell(0, 1).tag,
            default_value="XY Data", width=-1,
            callback=self._reference_type_changed)
        self._saved_list_view = self.own_widget(QListWidget(
            parent=self._library_panel_widget, width=-1, height=-1,
            context_menu_requests=True))
        self.saved_list = self._saved_list_view.tag
        self._saved_list_view.itemClicked.connect(
            self._series_list_clicked, receiver=self)
        self._saved_list_view.contextMenuRequested.connect(
            self._series_list_context_menu, receiver=self)

        self._details_panel_widget = self.own_widget(QFrame(
            parent=self._workspace_grid.cell(0, 1), width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self._details_panel_widget.setTheme(self._chart_layout_theme)
        # Series names are edited only through the Series context menu / inline
        # rename.  Keep a hidden compatibility buffer because formula editing
        # historically stores the active name in this control, but do not expose
        # a redundant name textbox in the dialog.
        self.name_edit = self.line_edit(
            self._next_default_name(), parent=self._details_panel_widget,
            width=1, callback=self._name_changed)
        self.control_wrapper(self.name_edit).hide()
        # XY Data needs only enough room for its columns and controls. Preview
        # is intentionally the elastic pane: when the dialog grows/shrinks,
        # the plot receives nearly all horizontal delta. The divider remains
        # draggable; a user drag simply establishes a new preferred XY width.
        self._authoring_splitter = self.own_widget(QSplitter(
            Qt.Horizontal, parent=self._details_panel_widget,
            after=self.view.after, handle_width=5))

        self._preview_frame = self.own_widget(QFrame(
            parent=self._authoring_splitter, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self._preview_frame.setTheme(self._chart_layout_theme)
        self._preview_header = self.own_widget(QGridLayout(
            4, column_widths=(58, None, 40, 80), parent=self._preview_frame,
            after=self.view.after, height=self.ROW_HEIGHT))
        QLabel('Preview', parent=self._preview_header.cell(0, 0))
        self._preview_message = self.own_widget(QLabel(
            'Click Refresh to preview edits.', parent=self._preview_header.cell(0, 1), wrap=260))
        self.preview_fit_button = self.action(
            'Fit', self._fit_preview, role='secondary',
            parent=self._preview_header.cell(0, 2).tag, width=34)
        self.preview_button = self.action(
            'Refresh', self._refresh_preview, role='secondary',
            parent=self._preview_header.cell(0, 3).tag, width=74)
        self.control_wrapper(self.preview_button).setToolTip(
            'Preview the current editor without saving. Formula uses available data from the active Plot.')
        self._preview_top_gap = self.own_widget(QSpacer(0, 10, parent=self._preview_frame))
        self._preview_plot = self.own_widget(QPlotWidget(
            parent=self._preview_frame, width=320, height=300, mouse_position=False))
        self._preview_plot.applyFusionTheme()
        self._preview_x_axis = self._preview_plot.addAxis(QPlotAxis.XAxis, 'X')
        self._preview_y_axis = self._preview_plot.addAxis(QPlotAxis.YAxis, 'Y')
        for axis in (self._preview_x_axis, self._preview_y_axis):
            axis.setHoverHighlightEnabled(False)

        self._series_menu = QMenu([
            {"id": "rename", "label": "Rename", "action": "rename",
             "icon": ResourceTextures.get("Rename")},
            {"id": "delete", "label": "Delete", "action": "delete",
             "icon": ResourceTextures.get("Delete")},
        ], after=self.view.after, min_width=146,
           parent_window=self.tag, parent=self)
        self._series_menu.triggered.connect(self._series_context_action)
        self._rename_input_binding = QGlobalInputBinding(parent=self)
        self._rename_input_binding.onMouseClick(Qt.LeftButton, self._rename_outside_click)
        self._rename_input_binding.activate()

        self._editor_panel_widget = self.own_widget(QFrame(
            parent=self._authoring_splitter, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self.editor_panel = self._editor_panel_widget.tag
        self._editor_panel_widget.setTheme(self._chart_layout_theme)
        self._editor_header = self.own_widget(QGridLayout(
            4, column_widths=(66, None, 154, 118),
            parent=self._editor_panel_widget, after=self.view.after,
            height=self.ROW_HEIGHT))
        QLabel("XY Data", parent=self._editor_header.cell(0, 0))
        self._xy_summary = self.own_widget(QLabel(
            "0 points", parent=self._editor_header.cell(0, 1), wrap=170))
        self.reduce_accuracy_combo = self.combo(
            tuple(name for name, _ratio in self.REDUCTION_PRESETS),
            parent=self._editor_header.cell(0, 2).tag,
            default_value=self.DEFAULT_REDUCTION_PRESET, width=-1)
        self.control_wrapper(self.reduce_accuracy_combo).setToolTip(
            "Maximum normalized geometric deviation allowed while reducing samples. "
            "Exact removes only duplicate/collinear points; High fidelity is the recommended default.")
        self.reduce_samples_button = self.action(
            "Reduce Samples", self._reduce_xy_samples, role="secondary",
            parent=self._editor_header.cell(0, 3).tag, width=112)
        self.control_wrapper(self.reduce_samples_button).setToolTip(
            "Remove redundant XY samples using error-bounded curve simplification. "
            "Endpoints, reversals and sharp turns are preserved. Repeated clicks reduce further: "
            "each pass is recomputed from the original XY source and automatically uses the smallest "
            "additional source-error bound needed to remove about 20% of the remaining points. Save is still required to persist the result.")

        self._formula_group_widget = self.own_widget(QFrame(
            parent=self._editor_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True,
            show=False))
        self.formula_group = self._formula_group_widget.tag
        self.formula_builder_button = self.action(
            'U/RF helper', self._toggle_formula_builder, parent=self.formula_group, width=-1)
        self._formula_builder_open = False
        self._formula_builder_widget = self.own_widget(QFrame(
            parent=self._formula_group_widget, width=-1,
            height=64,
            frame_shape=QFrame.NoFrame, show=False))
        self._generator_grid = self.own_widget(QGridLayout(
            2, column_widths=(None, 96), parent=self._formula_builder_widget,
            after=self.view.after, height=self.ROW_HEIGHT))
        self.generate_direction = self.combo(
            ("U1 / RF1", "U2 / RF2", "U3 / RF3", "All directions"),
            parent=self._generator_grid.cell(0, 0).tag, default_value="U3 / RF3", width=-1)
        self.generate_formula_button = self.action(
            "Generate", self._generate_ur_rf, parent=self._generator_grid.cell(0, 1).tag, width=90)
        self.control_wrapper(self.generate_formula_button).setToolTip(
            "Generate one U/RF formula per matching step/region in the active Plot. "
            "Without a Plot, generate unscoped regex templates instead.")
        self._generator_options = self.own_widget(QGridLayout(
            3, column_widths=(None, 58, 64), parent=self._formula_builder_widget,
            after=self.view.after, height=26))
        self.generate_antialiasing = self.checkbox(
            "ANTIALIASING", checked=True, parent=self._generator_options.cell(0, 0).tag)
        self.control_wrapper(self.generate_antialiasing).setToolTip(
            "Checked: match ANTIALIASING outputs. Unchecked: match raw U/RF outputs.")
        self.generate_reverse_u = self.checkbox(
            "-U", checked=False, parent=self._generator_options.cell(0, 1).tag)
        self.generate_reverse_rf = self.checkbox(
            "-RF", checked=True, parent=self._generator_options.cell(0, 2).tag)
        self._formula_label_grid = self.own_widget(QGridLayout(
            3, column_widths=(None, 102, 88), parent=self._formula_group_widget,
            after=self.view.after, height=self.ROW_HEIGHT))
        QLabel("Formula", parent=self._formula_label_grid.cell(0, 0))
        self.check_regex_button = self.action(
            "Check Regex", self._open_regex_tester, role="secondary",
            parent=self._formula_label_grid.cell(0, 1).tag, width=96)
        self.control_wrapper(self.check_regex_button).setToolTip(
            "Open a regex tester with Pattern, Test text, flags, matches and capture groups.")
        self.validate_formula_button = self.action(
            "Validate", self._validate_formula, role="secondary",
            parent=self._formula_label_grid.cell(0, 2).tag, width=82)
        self.control_wrapper(self.validate_formula_button).setToolTip(
            "Check formula syntax without saving the rule.")
        self.formula_edit = self.plain_text_edit(
            DEFAULT_FORMULA,
            parent=self.formula_group, width=-1, height=90,
            callback=self._formula_changed)
        # Keep the editor tooltip intentionally short. The previous multi-line
        # syntax reference covered the expression while the user was editing.
        # Detailed guidance lives below the editor and in the palette help row.
        self.control_wrapper(self.formula_edit).setToolTip(
            'Formula expression. Double-click a function/operator below to insert it.')
        self._formula_feedback = self.own_widget(QLabel(
            'Use regex("pattern") to select History Outputs. Math: + - * / ** %.',
            parent=self._formula_group_widget, wrap=430))
        self._formula_feedback.setToolTip(
            'Syntax is checked after a short pause. This does not evaluate Plot data or save the rule.\n'
            'Example: regex(".*RF3.*")/1000. Use 0.5 for 50%.')
        self._formula_examples_label = self.own_widget(QLabel(
            'Functions / Operators', parent=self._formula_group_widget))
        self._formula_search_grid = self.own_widget(QGridLayout(
            2, column_widths=(None, 74), parent=self._formula_group_widget,
            after=self.view.after, height=self.ROW_HEIGHT))
        self.formula_search = self.line_edit(
            '', parent=self._formula_search_grid.cell(0, 0).tag, width=-1,
            callback=self._filter_formula_functions)
        self.control_wrapper(self.formula_search).setPlaceholderText('Search functions / operators...')
        self.control_wrapper(self.formula_search).setToolTip('Search functions, operators or descriptions.')
        self.insert_formula_button = self.action(
            'Insert', self._insert_selected_function, role='secondary',
            parent=self._formula_search_grid.cell(0, 1).tag, width=68)
        self._formula_function_help = self.own_widget(QLabel(
            'Select an item to see its syntax and description.',
            parent=self._formula_group_widget, wrap=430))
        self._formula_functions_view = self.own_widget(QListWidget(
            parent=self._formula_group_widget, after=self.view.after,
            width=-1, height=-1))
        self.formula_functions = self._formula_functions_view.tag
        self._formula_function_items = []
        for fn_name, fn_syntax, fn_help in FORMULA_FUNCTIONS:
            item = QListWidgetItem(FORMULA_LABELS.get(fn_name, '{}(A)'.format(fn_name)))
            item.setData(Qt.UserRole, (fn_name, fn_syntax, fn_help))
            self._formula_function_items.append(item)
        # Populate the function palette in one native batch rather than
        # rebuilding it once per function during dialog startup.
        self._formula_functions_view.addItems(self._formula_function_items)
        # Single-click exposes concise syntax/help without changing the draft;
        # double-click inserts the selected function/operator.
        self._formula_functions_view.itemClicked.connect(
            self._formula_palette_clicked, receiver=self)
        self._formula_functions_view.itemDoubleClicked.connect(
            self._formula_palette_double_clicked, receiver=self)

        self.data_table = ReferenceDataTable(
            self._editor_panel_widget, self.view.after, self._input_error,
            height=-1, menu_parent=self.tag,
            on_import=self._import_clipboard,
            on_change=self._mark_xy_data_dirty)
        # Put the primary worksheet first even though Preview is constructed
        # earlier. Start compact; _sync_authoring_split_sizes() keeps this width
        # stable while assigning all remaining horizontal space to Preview.
        self._authoring_splitter.addWidget(self._editor_panel_widget)
        self._authoring_splitter.addWidget(self._preview_frame)
        self._authoring_splitter.setSizes([self.EDITOR_DEFAULT_WIDTH, 1000])
        self._authoring_splitter.splitterMoved.connect(
            self._authoring_splitter_moved, receiver=self)
        self._clipboard = QClipboard()
        # Native table-column resizing changes pane widths without resizing
        # the dialog itself. Keep wrapping and the worksheet geometry in sync.
        self._pane_resize_bindings = [
            QItemInputBinding(pane, parent=self).onResize(
                lambda *_args: self._sync_pane_geometry()).activate()
            for pane in (self._library_panel_widget, self._editor_panel_widget, self._preview_frame)]

        self.status = self.status_text("", parent=self.content)
        self.button_box([
            ("Save", self._save, "primary", True),
            ("Cancel", lambda: self.finish(None), "secondary", False),
        ], status_item=self.status)
        self._refresh_list(select_first=True)
        if self._series:
            self._load_item(self._series[0])
        else:
            self._new_input()
        self.view.after(1, self._sync_pane_geometry)
        # Native rows are populated only after the dialog has had a chance to
        # present. The hook merely ensures the deferred pass is running; it does
        # not synchronously walk the dataset.
        self.view.after(1, self.data_table.refresh_visible_page)
        self.view.after(1, self.data_table.focus_cell, 0, 0)
        self.view.after(1, self._update_size_constraints, True)

    def layout_dialog(self):
        if getattr(self, "_finished", False):
            return
        try:
            self.view.after(1, self._sync_pane_geometry)
        except Exception:
            pass

    def _sync_pane_geometry(self):
        if self._finished or not self.winfo_exists() or self._pane_geometry_syncing:
            return
        self._pane_geometry_syncing = True
        try:
            self._library_panel_widget.resize(-1, -1)
            self._details_panel_widget.resize(-1, -1)
            self._authoring_splitter.resize(-1, -1)
            self._sync_authoring_split_sizes()
            self.data_table.resize(-1, -1)
            self._saved_list_view.resize(-1, -1)
            # Fill-width widgets retain width=-1; use their measured client
            # rectangles, not width(), when calculating text wrapping.
            editor_width = self._editor_panel_widget.globalGeometry().width()
            preview_width = self._preview_frame.globalGeometry().width()
            if editor_width > 100:
                self._formula_feedback.setWrapWidth(editor_width - 4)
                self._formula_function_help.setWrapWidth(editor_width - 4)
            if preview_width > 100:
                # The summary now lives in the Preview header, so the plot can
                # consume the full body height.  This removes the visually
                # detached status row under the chart and keeps both authoring
                # panes aligned at the bottom.
                self._preview_message.setWrapWidth(max(120, preview_width - 190))
                preview_geometry = self._preview_frame.globalGeometry()
                preview_height = preview_geometry.height()
                if preview_height > 160:
                    plot_width = max(100, int(preview_width) - 10)
                    plot_geometry = self._preview_plot.globalGeometry()
                    preview_bottom = int(preview_geometry.y() + preview_geometry.height())
                    plot_top = int(plot_geometry.y())
                    bottom_inset = 4
                    measured_height = preview_bottom - plot_top - bottom_inset
                    if plot_top <= 0 or measured_height <= 0:
                        measured_height = int(preview_height) - 42
                    plot_height = max(100, int(measured_height))
                    plot_size = (plot_width, plot_height)
                    if getattr(self, '_preview_plot_size', None) != plot_size:
                        self._preview_plot.resize(*plot_size)
                        self._preview_plot_size = plot_size
            self._update_size_constraints()
        except Exception:
            pass
        finally:
            self._pane_geometry_syncing = False

    def _sync_authoring_split_sizes(self):
        """Keep XY Data compact and let Preview absorb host-width changes.

        QSplitter normally preserves proportional weights. Reference Chart uses
        Qt-style stretch semantics instead: the worksheet is a preferred/fixed
        pane and Preview/Plots is the stretch pane. A manual divider drag
        updates ``_editor_preferred_width``; subsequent dialog resizes preserve
        that width whenever the Preview minimum can still be respected.
        """
        try:
            splitter_width = int(self._authoring_splitter.globalGeometry().width())
            handle_width = int(self._authoring_splitter.handleWidth())
        except Exception:
            return
        if splitter_width <= handle_width + 2:
            return
        available = max(2, splitter_width - handle_width)
        preferred = max(self.EDITOR_MIN_WIDTH, int(self._editor_preferred_width))
        if available >= self.EDITOR_MIN_WIDTH + self.PREVIEW_MIN_WIDTH:
            editor = min(preferred, available - self.PREVIEW_MIN_WIDTH)
            preview = available - editor
        else:
            # At the absolute minimum dialog width, degrade gracefully while
            # keeping both panes visible. Preview still receives the remainder.
            editor = min(preferred, max(1, available - 1))
            preview = max(1, available - editor)
        current = self._authoring_splitter.sizes()
        target = [int(editor), int(preview)]
        if len(current) != 2 or any(abs(int(a) - int(b)) > 1 for a, b in zip(current, target)):
            self._authoring_splitter.setSizes(target)

    def _authoring_splitter_moved(self, *_args):
        """Store the user-selected XY width; Preview remains the stretch pane."""
        try:
            sizes = self._authoring_splitter.sizes()
            if len(sizes) != 2:
                return
            total = max(2, int(sum(sizes)))
            editor = max(1, int(sizes[0]))
            preview = max(1, int(sizes[1]))
            if total >= self.EDITOR_MIN_WIDTH + self.PREVIEW_MIN_WIDTH:
                editor = max(self.EDITOR_MIN_WIDTH, min(editor, total - self.PREVIEW_MIN_WIDTH))
                preview = total - editor
                if [editor, preview] != list(sizes):
                    self._authoring_splitter.setSizes([editor, preview])
            self._editor_preferred_width = int(editor)
            self.view.after(1, self._sync_pane_geometry)
        except Exception:
            pass

    def _sync_xy_summary(self, count=None):
        if not hasattr(self, '_xy_summary'):
            return
        if count is None:
            try:
                count = int(self.data_table.model.row_count)
            except Exception:
                count = 0
        self._xy_summary.setText('{:,} point{}'.format(
            int(count), '' if int(count) == 1 else 's'))

    def _update_size_constraints(self, force_resize=False):
        min_width = self.FORMULA_MIN_WIDTH if self._formula_mode else self.XY_MIN_WIDTH
        try:
            self.setMinimumSize(min_width, self.MIN_HEIGHT)
        except Exception:
            try:
                self.setMinimumWidth(min_width)
                self.setMinimumHeight(self.MIN_HEIGHT)
            except Exception:
                pass
        try:
            current_width = int(self.width or 0)
        except Exception:
            current_width = 0
        try:
            current_height = int(self.height or 0)
        except Exception:
            current_height = 0
        try:
            actual_width, actual_height = dpg.get_item_rect_size(self.tag)
            if actual_width > 0 and actual_height > 0:
                current_width, current_height = int(actual_width), int(actual_height)
        except (KeyError, TypeError, ValueError, RuntimeError):
            pass
        # Some native backends do not retroactively resize an already-visible
        # window when its minimum size changes. Clamp immediately whenever the
        # current geometry is below the active mode's safe layout size.
        if force_resize or current_width < min_width or current_height < self.MIN_HEIGHT:
            try:
                self.resize(max(current_width, min_width),
                            max(current_height, self.MIN_HEIGHT))
            except Exception:
                pass

    def _next_default_name(self):
        used = {str(item.get("name") or "").strip().casefold() for item in self._series}
        index = 1
        while True:
            name = "Reference {}".format(index)
            if name.casefold() not in used:
                return name
            index += 1



































































    def finish(self, result):
        if self._finished:
            return
        self._finished = True
        try:
            self.on_result(result)
        finally:
            self.destroy()

    def _close_from_escape(self):
        self.finish(None)

    def invoke_default(self):
        if isinstance(self.focusWidget(), QPushButton):
            return super().invoke_default()
        if self._formula_mode:
            wrapper = self.control_wrapper(self.formula_edit)
            try:
                if wrapper is not None and wrapper.hasFocus():
                    return
            except Exception:
                pass
        if not self.data_table.owns_keyboard():
            super().invoke_default()

    def _handle_key_event(self, event):
        table = getattr(self, "data_table", None)
        if (table is not None and table.owns_keyboard()
                and event.key() in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter)):
            # The worksheet's key binding commits/navigates cells. Do not let
            # QDialog also move focus to another form control or press Save.
            return True
        return super()._handle_key_event(event)

    def destroy(self):
        table = getattr(self, "data_table", None)
        if table is not None:
            if getattr(self, "_defer_visual_destroy", False):
                table.suspend()
            else:
                table.delete()
        super().destroy()

    def _finalize_visual_destroy(self, *_args, **_kwargs):
        table = getattr(self, "data_table", None)
        if table is not None:
            table.delete()
        super()._finalize_visual_destroy()
