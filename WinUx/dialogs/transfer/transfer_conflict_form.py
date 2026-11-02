"""Batch or per-item overwrite decisions; nested directory conflicts are separate."""
from datetime import datetime
from pathlib import PurePath
import threading

from DearUIQt.backends import dpg
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.widgets import QtTable, QLabel
from DearUIQt.layouts import QGridLayout
from DearUIQt.gui.style import METRICS
from DearUIQt.modelview.themes import qt_item_view_theme
from ...ui.hosting.inprocess_dialog import TransientInProcessDialogMixin
from ...services.transfer.tree import TreeReview


def _row_theme():
    tag = 'winux.transfer_conflict.row'
    if not dpg.does_item_exist(tag):
        with dpg.theme(tag=tag):
            with dpg.theme_component(dpg.mvSelectable):
                dpg.add_theme_color(dpg.mvThemeCol_Header, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_SelectableTextAlign, 0, .5)
    return tag


def _table_theme():
    return qt_item_view_theme(dpg)


class _ConflictTable(QtTable):
    """Keep row selection functional without the blue native selection fill."""

    def _sync_selection_visuals(self):
        super()._sync_selection_visuals()
        # The base view rebinds themes on current/selection/focus changes.
        # Apply our quiet row style after every such update, not just creation.
        for item in self.items.values():
            dpg.bind_item_theme(item, _row_theme())


class TransferConflictDialog(TransientInProcessDialogMixin, QtDialog):
    PAGE_SIZE = 200
    ACTIONS = {'Skip': 'skip', 'Replace': 'replace', 'Newer only': 'newer', 'Rename file': 'rename'}
    ACTION_LABELS = {'skip': 'Skip', 'replace': 'Replace', 'newer': 'Newer only', 'rename': 'Rename'}

    def __init__(self, view, review, on_result, on_review_contents=None):
        self.review = review
        self._on_result = on_result
        self._finished = False
        self._overrides = {}
        self._conflicts = [source for source in review.sources if review.target_states[str(source)] is not None]
        self._page = 0
        self._editing_index = None
        self._syncing = False
        self._on_review_contents = on_review_contents
        self._scanning = False
        self._scan_cancel = self._scan_token = None
        self._row_combos = {}
        self._size_cells = {}
        self.item_action = None
        table_height = self._table_height(len(self._conflicts))
        super().__init__(view, 'Files already exist', 700, 142 + table_height, compact=True)
        self.note('{} -> {}   •   {}'.format(
            review.source_panel.title(), review.target_panel.title(), review.destination), wrap=700)
        self.table = self.own_widget(_ConflictTable(self.content, (
            {'key': 'name', 'label': 'Name', 'stretch': 3, 'sortable': False},
            {'key': 'size', 'label': 'Size (source -> existing)', 'width': 190, 'sortable': False},
            {'key': 'action', 'label': 'Action', 'width': 110, 'sortable': False},
        ), height=table_height, multiple=False))
        dpg.configure_item(self.table.tag, scrollX=False)
        action_column = dpg.get_item_children(self.table.tag, 0)[2]
        dpg.configure_item(action_column, no_resize=True)
        dpg.bind_item_theme(self.table.tag, _table_theme())
        # DPG assigns a column to every direct table-row child, even a hidden
        # one. Keep replaced text cells outside the row so editors occupy the
        # third column rather than a clipped fourth column.
        self._cell_placeholders = dpg.add_group(parent=self.content, show=False)
        with dpg.group(parent=self.content, horizontal=True) as pages:
            self.pages_group = pages
            self.previous_page = self.action('Previous', lambda: self._change_page(-1), parent=pages)
            self.next_page = self.action('Next', lambda: self._change_page(1), parent=pages)
            self.contents_button = self.action('Review contents...', self._start_contents,
                                              parent=pages, width=135)
            self.details_button = self.action('Details...', self._toggle_details, parent=pages, width=82)
        self.page_note = self.note('', wrap=700)
        self._rename_grid = self.own_widget(QGridLayout(
            2, column_widths=(68, None), parent=self.contentWidget(),
            after=self.view.after, height=32))
        QLabel('Rename to', parent=self._rename_grid.cell(0, 0))
        self.item_name = self.line_edit(
            '', parent=self._rename_grid.cell(0, 1).tag, width=-1,
            hint='New name in the same destination folder')
        self._rename_grid.setVisible(False)
        self.table.selectionChanged.connect(self._selection_changed, receiver=self)
        with dpg.group(parent=self.content, show=False) as details_group:
            self.details_group = details_group
            self.item_details = self.note('', parent=details_group, wrap=640)
            self.scope_note = self.note(
                'Advanced review can inspect folder contents recursively. Scanning only previews conflicts; '
                'it never copies or deletes files.', parent=details_group, wrap=700)
            self.selected_meta_note = self.note('', parent=details_group, wrap=700)
            self.policy_note = self.note(
                'Newer only replaces regular files when the source is more than 2 seconds newer. '
                'Folders, links, equal/older files and uncertain timestamps are skipped. Rename is available '
                'for regular files only and never overwrites the renamed target.', parent=details_group, wrap=700)
        self.status = self.status_text(wrap=770)
        self.decision_buttons = self.button_box([
            ('Replace All', lambda: self._finish('replace'), 'secondary', False),
            ('OK', lambda: self._finish('custom'), 'secondary', False),
            ('Cancel', self._close_from_escape, 'secondary', False),
        ], status_item=self.status, status_above_buttons=True)
        self._init_inprocess_lifetime(view)
        self._render_rows(0 if self._conflicts else None)

    @staticmethod
    def _table_height(count):
        return 26 + (METRICS.control_height + 2) * max(1, min(count, 6))

    def _render_rows(self, selected=None):
        self._syncing = True
        try:
            start = self._page * self.PAGE_SIZE
            rows = []
            for index in range(start, min(start + self.PAGE_SIZE, len(self._conflicts))):
                source = self._conflicts[index]
                key = str(source)
                action, name = self._overrides.get(key, ('skip', None))
                rows.append((index, (
                    self._display_name(source),
                    '{} -> {}'.format(self._size(self.review.source_states[key]),
                                     self._size(self.review.target_states[key])),
                    self.ACTION_LABELS.get(action, action.title()),
                )))
            for group, text in self._size_cells.values():
                # Restore the keyed text item before updating/rebuilding rows.
                dpg.move_item(text, before=group)
                dpg.delete_item(group)
            self._size_cells.clear()
            for combo in self._row_combos.values():
                for tag, wrapper in tuple(self._control_wrappers.items()):
                    if wrapper is combo:
                        self._control_wrappers.pop(tag, None)
                        if tag in self._focus_order:
                            self._focus_order.remove(tag)
                combo.delete()
            self._row_combos.clear()
            self.item_action = None
            self.table.set_rows(rows)
            retained = {cell for cells in self.table._cell_native_items.values() for cell in cells[1:]}
            for tag in dpg.get_item_children(self._cell_placeholders, 1) or ():
                if tag not in retained:
                    dpg.delete_item(tag)
            self.table.setFixedHeight(self._table_height(len(rows)))
            for row, (index, values) in enumerate(rows):
                row_tag = self.table._row_tags[index]
                name_cell, size_cell, _ = self.table._cell_native_items[index]
                dpg.configure_item(name_cell, height=METRICS.control_height)
                dpg.bind_item_theme(name_cell, _row_theme())
                # Use the same vertically centered renderer for both text
                # columns. Plain DPG text is always top-aligned in a table.
                group = dpg.add_selectable(
                    parent=row_tag, before=size_cell, label=values[1],
                    height=METRICS.control_height, span_columns=False,
                    callback=lambda *_, i=index: self.table.setCurrentKey(i))
                dpg.bind_item_theme(group, _row_theme())
                dpg.move_item(size_cell, parent=self._cell_placeholders)
                self._size_cells[index] = (group, size_cell)
                action = self._overrides.get(str(self._conflicts[index]), ('skip', None))[0]
                label = next(label for label, value in self.ACTIONS.items() if value == action)
                tag = self.combo(list(self.ACTIONS), parent=self.content, default_value=label)
                combo = self._control_wrappers[tag]
                # QtTable's keyed rows have no QAbstractItemModel. Mount the
                # editor in the action cell, replacing its display-only text.
                dpg.move_item(combo.tag, parent=self.table._row_tags[index])
                dpg.move_item(self.table._cell_native_items[index][2], parent=self._cell_placeholders)
                combo.currentTextChanged.connect(
                    lambda text, i=index: self._row_action_changed(i, text), receiver=self)
                self._row_combos[index] = combo
            self.table.selected.clear()
            self._editing_index = selected
            if selected is not None:
                self.table.setCurrentKey(selected)
            multiple_pages = len(self._conflicts) > self.PAGE_SIZE
            self.set_control_visible(self.previous_page, multiple_pages)
            self.set_control_visible(self.next_page, multiple_pages)
            self.set_control_visible(self.page_note, multiple_pages)
            self.set_control_value(self.page_note, '{}-{} of {} conflicts'.format(
                start + 1 if rows else 0, start + len(rows), len(self._conflicts)))
            self.set_control_enabled(self.previous_page, self._page > 0)
            self.set_control_enabled(self.next_page, start + self.PAGE_SIZE < len(self._conflicts))
            can_review_contents = (callable(self._on_review_contents) and
                not isinstance(self.review, TreeReview) and any(state is not None and state.directory
                    for state in self.review.source_states.values()))
            self.set_control_visible(self.contents_button, can_review_contents)
            self.set_control_enabled(self.contents_button, can_review_contents)
            self._load_editor()
        finally:
            self._syncing = False

    def _display_name(self, source):
        return self.review.display_name(source) if isinstance(self.review, TreeReview) else source.name

    def _row_action_changed(self, index, text):
        if self._syncing or self._scanning:
            return
        if index != self._editing_index:
            self._selection_changed({index})
        if index == self._editing_index:
            self._syncing = True
            try:
                self.set_control_value(self.item_action, text)
            finally:
                self._syncing = False
            self._action_changed()

    def _toggle_details(self):
        try:
            shown = bool(dpg.get_item_configuration(self.details_group).get('show', False))
        except Exception:
            shown = False
        self.set_control_visible(self.details_group, not shown)
        self.set_control_value(self.details_button, 'Less' if not shown else 'Details...')

    def _start_contents(self):
        if not self._scanning and callable(self._on_review_contents):
            self._on_review_contents(self)

    def begin_contents_scan(self):
        if self._scan_cancel is not None:
            self._scan_cancel.set()
        self._scan_cancel, self._scan_token = threading.Event(), object()
        self._scanning = True
        self.table.setEnabled(False)
        for combo in self._row_combos.values():
            combo.setEnabled(False)
        for tag in (self.contents_button, self.previous_page, self.next_page, self.item_action,
                    self.item_name, *self.decision_buttons[:-1]):
            self.set_control_enabled(tag, False)
        self.set_control_value(self.status, 'Scanning: 10,000 items / 32 levels / 30s budget. Cancel interrupts between server requests.')
        return self._scan_cancel, self._scan_token

    def finish_contents_scan(self, review=None, error=None):
        if self._finished:
            return
        self._scanning = False
        self.table.setEnabled(True)
        for tag in self.decision_buttons:
            self.set_control_enabled(tag, True)
        if review is not None:
            self.review = review
            self._overrides = {}
            self._conflicts = [source for source in review.sources if review.target_states[str(source)] is not None]
            self._page = 0
            self.set_control_value(self.scope_note, 'Recursive review: choices apply to the listed leaf files and empty folders. '
                'Folder structure is preserved; links/type conflicts stop the scan. Nothing is deleted. '
                'A queued copy revalidates the snapshot; Retry requires a fresh contents review.')
        self._render_rows(0 if self._conflicts else None)
        self.set_control_value(self.status, error or '{} leaf item(s), {} conflict(s). Review and confirm before copying.'.format(
            len(self.review.sources), len(self._conflicts)))

    def _load_editor(self):
        index = self._editing_index
        if index is None:
            self.set_control_value(self.item_details, 'Select an item to change its action.')
            self.set_control_enabled(self.item_action, False)
            self.set_control_enabled(self.item_name, False)
            self._rename_grid.setVisible(False)
            return
        source = self._conflicts[index]
        self.item_action = self._row_combos[index].tag
        key = str(source)
        left, right = self.review.source_states[key], self.review.target_states[key]
        action, name = self._overrides.get(key, ('skip', None))
        self.set_control_value(self.item_details, '{}   •   {} -> {}'.format(
            self._display_name(source), self._size(left), self._size(right)))
        self.set_control_value(self.selected_meta_note,
            'Selected item: {}\nSource modified: {}   Existing modified: {}\nSource path: {}'.format(
                self._display_name(source), self._date(left), self._date(right), source))
        self.set_control_enabled(self.item_action, True)
        self.set_control_value(self.item_action, next(label for label, value in self.ACTIONS.items() if value == action))
        path = PurePath(source.name)
        self.set_control_value(self.item_name, name or '{}-copy{}'.format(path.stem, path.suffix))
        self._action_changed()

    def _action_changed(self):
        rename = (self._editing_index is not None and
                  self.control_value(self.item_action) == 'Rename file')
        self._rename_grid.setVisible(rename)
        self.set_control_enabled(self.item_name, rename)
        if not self._syncing and not rename:
            self._set_selected()

    def _store_editor(self):
        if self._editing_index is None:
            return
        source = self._conflicts[self._editing_index]
        action = self.ACTIONS[self.control_value(self.item_action)]
        name = self.control_value(self.item_name) if action == 'rename' else None
        candidate = dict(self._overrides)
        candidate[str(source)] = (action, name)
        self.review.choose('custom', candidate)  # Validate before changing the draft.
        self._overrides = candidate

    def _set_selected(self):
        if self._scanning:
            return
        try:
            self._store_editor()
            self._render_rows(self._editing_index)
            self.set_control_value(self.status, '')
        except (ValueError, OSError) as exc:
            self.set_control_value(self.status, str(exc))

    def _selection_changed(self, selected):
        if self._syncing or self._scanning:
            return
        previous = self._editing_index
        try:
            self._store_editor()
            self._render_rows(next(iter(selected), None))
        except (ValueError, OSError) as exc:
            self._render_rows(previous)
            self.set_control_value(self.status, str(exc))

    def _change_page(self, amount):
        if self._scanning:
            return
        try:
            self._store_editor()
            target = self._page + amount
            if 0 <= target <= max(0, (len(self._conflicts) - 1) // self.PAGE_SIZE):
                self._page = target
                self._render_rows(target * self.PAGE_SIZE if self._conflicts else None)
        except (ValueError, OSError) as exc:
            self.set_control_value(self.status, str(exc))

    @staticmethod
    def _size(state):
        if state is None:
            return 'Missing'
        if not state.regular:
            return state.kind
        size = max(0, int(state.size or 0))
        value = float(size)
        units = ('B', 'KB', 'MB', 'GB', 'TB')
        unit = units[0]
        for candidate in units:
            unit = candidate
            if value < 1024.0 or candidate == units[-1]:
                break
            value /= 1024.0
        if unit == 'B':
            return '{} B'.format(int(value))
        if value >= 100:
            return '{:.0f} {}'.format(value, unit)
        if value >= 10:
            return '{:.1f} {}'.format(value, unit)
        return '{:.2f} {}'.format(value, unit)

    @staticmethod
    def _date(state):
        if state is None:
            return '-'
        try:
            return datetime.fromtimestamp(state.modified).strftime('%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError, OverflowError, OSError):
            return 'Unknown'

    def _finish(self, policy=None):
        if self._finished:
            return
        if self._scanning and policy is not None:
            return
        if self._scan_cancel is not None:
            self._scan_cancel.set()
        try:
            if policy == 'custom':
                self._store_editor()
            decision = self.review.choose(policy, self._overrides if policy == 'custom' else None) if policy else None
        except (ValueError, OSError) as exc:
            self.set_control_value(self.status, str(exc))
            return
        self._finished = True
        try:
            self._on_result(decision)
        finally:
            self.destroy()

    def _close_from_escape(self):
        self._finish()

    def destroy(self):
        if self._scan_cancel is not None:
            self._scan_cancel.set()
        if not self._finished:
            self._finished = True
            self._on_result(None)
        super().destroy()
