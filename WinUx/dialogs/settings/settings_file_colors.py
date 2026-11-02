"""Settings rule-list/editor patterned after WinSCP's File Colors page."""
from DearUIQt.backends import dpg
from DearUIQt.modelview import QListWidget, QListWidgetItem
from DearUIQt.widgets import QCheckBox, QLabel
from DearUIQt.widgets.color_field import ColorField

from ...services.file_color_rules import (
    SCOPES, MAX_RULES, color_hex, default_color_rules, normalize_color_rules,
)


class FileColorSettingsMixin:
    def _build_colors_page(self, page, general):
        self.header('File Colors', 'Ordered filename-color rules for Local and Server.', parent=page)
        self._color_rules_draft = normalize_color_rules(general.get('file_color_rules'))
        self._color_rule_index = None
        self._syncing_color_rules = False
        with self.section('Rules (first matching enabled rule wins)', parent=page) as section:
            self.color_rule_list = self.own_widget(QListWidget(
                parent=self._qt_parent(section), after=self.view.after, backend=dpg,
                width=-1, visible_rows=6))
            self.color_rule_list.currentItemChanged.connect(self._color_rule_selected, receiver=self)
            with dpg.group(parent=section, horizontal=True, horizontal_spacing=6) as buttons:
                self._color_rule_buttons = {}
                for text, action in (('Add', 'add'), ('Update', 'update'), ('Remove', 'remove'),
                                     ('Up', 'up'), ('Down', 'down')):
                    self._color_rule_buttons[action] = self.action(
                        text, lambda action=action: self._edit_color_rule(action),
                        'secondary', parent=buttons, width=64)
            self.action('Restore Color Defaults', self._restore_color_defaults,
                        'secondary', parent=section, width=180)
        with self.section('Selected rule', parent=page) as editor:
            form = self.form_layout(parent=editor, label_width=88)
            self.color_rule_name = self.form_layout_row(
                form, 'Name', lambda parent: self.line_edit('', parent=parent, width=-1))
            self.color_rule_mask = self.form_layout_row(
                form, 'File mask', lambda parent: self.line_edit(
                    '*', parent=parent, width=-1, hint='*.inp;*.odb|*.bak'))
            self.color_rule_scope = self.form_layout_row(
                form, 'Apply to', lambda parent: self.combo(list(SCOPES.values()), parent=parent,
                                                           default_value=SCOPES['any']))
            def color_field(parent):
                self.color_rule_color = self.own_widget(ColorField(
                    self._qt_parent(parent), after=self.view.after, backend=dpg))
                self.color_rule_color.changed.connect(self._preview_rule_color, receiver=self)
                return self.color_rule_color.tag
            self.form_layout_row(form, 'Color', color_field)
            self._color_rule_enabled = self.own_widget(QCheckBox(
                'Enable this rule', checked=True, parent=editor, after=self.view.after, backend=dpg))
            self.color_rule_preview = QLabel('Filename preview: model.inp', parent=editor, backend=dpg).tag
            self.note('Masks: * and ?; lists separated by ; or ,; exclusions after |. '
                      '*.* also matches names without extensions; *. matches extensionless names. '
                      'Use */ for folders, */results/*.odb for paths, *.odb>1G for size, '
                      'or *.log<30D for files older than 30 days. Matching ignores case.',
                      parent=editor, wrap=400)
            self.note('Double a separator/operator to match it literally: ;; ,, || << >>. '
                      'Dates use YYYY-MM-DD [HH:MM[:SS]] in local time; intervals support D/H/N/S, '
                      'today and yesterday. Operation-relative paths, year intervals and rounded '
                      'intervals are not supported yet.', parent=editor, wrap=400)
            self.note('Selection keeps its normal text color. Changes apply only after Save; Cancel discards them.',
                      parent=editor, wrap=400)
        self._refresh_color_rule_list(0)

    def _rule_list_label(self, index, rule):
        return '{}. [{}] {}  |  {}  |  {}'.format(
            index + 1, 'On' if rule['enabled'] else 'Off', rule['name'], rule['mask'], rule['color'])

    def _refresh_color_rule_list(self, index):
        self._syncing_color_rules = True
        try:
            self.color_rule_list.clear()
            self.color_rule_list.addItems([
                QListWidgetItem(self._rule_list_label(i, rule))
                for i, rule in enumerate(self._color_rules_draft)])
            index = max(0, min(index, len(self._color_rules_draft) - 1)) if self._color_rules_draft else None
            self._color_rule_index = index
            if index is not None:
                self.color_rule_list.setCurrentRow(index)
            self._load_color_rule_editor()
        finally:
            self._syncing_color_rules = False

    def _load_color_rule_editor(self):
        index = self._color_rule_index
        rule = self._color_rules_draft[index] if index is not None else dict(
            name='', mask='*', scope='any', enabled=True, color='#0046A5')
        self.set_control_value(self.color_rule_name, rule['name'])
        self.set_control_value(self.color_rule_mask, rule['mask'])
        self.set_control_value(self.color_rule_scope, SCOPES[rule['scope']])
        self.set_control_value(self._color_rule_enabled.tag, rule['enabled'])
        rgb = tuple(int(rule['color'][i:i + 2], 16) for i in (1, 3, 5))
        self.color_rule_color.setColor(rgb)
        self._preview_rule_color(rule['color'])
        for tag in (self.color_rule_name, self.color_rule_mask, self.color_rule_scope,
                    self._color_rule_enabled.tag):
            self.set_control_enabled(tag, index is not None)
        self.color_rule_color.setEnabled(index is not None)
        for action, tag in self._color_rule_buttons.items():
            enabled = index is not None
            if action == 'add':
                enabled = len(self._color_rules_draft) < MAX_RULES
            elif action == 'up':
                enabled = index is not None and index > 0
            elif action == 'down':
                enabled = index is not None and index + 1 < len(self._color_rules_draft)
            self.set_control_enabled(tag, enabled)

    def _preview_rule_color(self, value):
        try:
            value = color_hex(value)
        except ValueError:
            return
        rgb = tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
        self.color_rule_color.setColor(rgb)
        dpg.configure_item(self.color_rule_preview, color=(*rgb, 255))

    def _commit_color_rule_editor(self):
        index = self._color_rule_index
        if index is None:
            return
        label = self.control_value(self.color_rule_scope)
        rule = dict(name=self.control_value(self.color_rule_name),
                    mask=self.control_value(self.color_rule_mask),
                    scope=next(key for key, value in SCOPES.items() if value == label),
                    enabled=bool(self.control_value(self._color_rule_enabled.tag)),
                    color=self.color_rule_color.editor.text())
        self._color_rules_draft[index] = normalize_color_rules([rule])[0]
        self.color_rule_list.item(index).setText(self._rule_list_label(index, self._color_rules_draft[index]))

    def _color_rule_selected(self, current, previous):
        if self._syncing_color_rules:
            return
        try:
            self._commit_color_rule_editor()
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            self._syncing_color_rules = True
            try:
                self.color_rule_list.setCurrentRow(self._color_rule_index)
            finally:
                self._syncing_color_rules = False
            return
        row = self.color_rule_list.row(current) if current is not None else -1
        self._color_rule_index = row if row >= 0 else None
        self._load_color_rule_editor()

    def _edit_color_rule(self, action):
        index = self._color_rule_index
        try:
            if action != 'remove':
                self._commit_color_rule_editor()
            if action == 'add':
                if len(self._color_rules_draft) >= MAX_RULES:
                    raise ValueError('At most {} rules are supported.'.format(MAX_RULES))
                index = index if index is not None else len(self._color_rules_draft)
                self._color_rules_draft.insert(index, dict(name='New rule', mask='*.inp;*.odb',
                    scope='file', color='#0046A5', enabled=True))
            elif index is None:
                return
            elif action == 'remove':
                self._color_rules_draft.pop(index)
            elif action in ('up', 'down'):
                target = index + (-1 if action == 'up' else 1)
                if not 0 <= target < len(self._color_rules_draft):
                    return
                self._color_rules_draft[index], self._color_rules_draft[target] = (
                    self._color_rules_draft[target], self._color_rules_draft[index])
                index = target
            self._refresh_color_rule_list(index)
            self._set_status('Color rules changed. Click Save to apply.')
        except ValueError as exc:
            self._set_status(str(exc), error=True)

    def _restore_color_defaults(self):
        self._color_rules_draft = default_color_rules()
        self._refresh_color_rule_list(0)

    def _collect_color_rules(self):
        self._commit_color_rule_editor()
        return normalize_color_rules(self._color_rules_draft)
