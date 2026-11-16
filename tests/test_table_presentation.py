"""Common data-table palette and behavior: abaqus python tests/test_table_presentation.py."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.dialogs.theme import dialog_theme
from DearUIQt.gui.palette import QtFusionPalette as P, QtFusionMetrics as M
from DearUIQt.modelview import QTableWidget, QTableWidgetItem, QtDataGridView, QtGridRow
from DearUIQt.modelview.themes import qt_item_view_theme
from DearUIQt.themes import worksheet_theme_spec
from DearUIQt.themes.spec import create_theme
from DearUIQt.widgets import QWidget
from WinUx.dialogs.job_table_style import _job_table_theme, style_job_table
from WinUx.dialogs.transfer_conflict_form import _table_theme


def table_roles(theme):
    for component in dpg.get_item_children(theme, 1):
        config = dpg.get_item_configuration(component)
        if config['item_type'] == dpg.mvTable and config['enabled_state']:
            return {((('style', dpg.get_item_configuration(item)['target']))
                     if dpg.get_item_type(item).endswith('mvThemeStyle')
                     else dpg.get_item_configuration(item)['target']): tuple(dpg.get_value(item))
                    for item in dpg.get_item_children(component, 1)}
    raise AssertionError('Missing table theme component')


def main():
    dpg.create_context()
    try:
        expected = {
            dpg.mvThemeCol_TableHeaderBg: P.TABLE_HEADER,
            dpg.mvThemeCol_TableBorderStrong: P.TABLE_BORDER,
            dpg.mvThemeCol_TableBorderLight: P.TABLE_GRID,
            dpg.mvThemeCol_TableRowBg: P.TABLE_ROW,
            dpg.mvThemeCol_TableRowBgAlt: P.TABLE_ROW_ALT,
        }
        shared = qt_item_view_theme(dpg)
        worksheet = create_theme(worksheet_theme_spec(), backend=dpg)
        for theme in (shared, dialog_theme(), worksheet, _job_table_theme(), _table_theme()):
            roles = table_roles(theme)
            for role, value in expected.items():
                assert roles[role] == value, (theme, role, roles[role], value)
            assert roles['style', dpg.mvStyleVar_CellPadding][:2] == M.TABLE_CELL_PADDING
        assert _job_table_theme() == _table_theme() == shared

        with dpg.window(show=False) as root:
            pass
        parent = QWidget(root, backend=dpg)
        table = QTableWidget(2, 2, parent=parent, backend=dpg)
        assert dpg.get_item_theme(table.tag) == shared
        table.setHorizontalHeaderLabels(['X', 'Y'])
        table.setItem(0, 0, QTableWidgetItem('10'))
        first = table.nativeRow(0)
        table.setRowCount(3)
        assert table.nativeRow(0) == first and table.item(0, 0).text() == '10'
        grid = QtDataGridView(parent, [{'key': 'name', 'label': 'Name'},
                                      {'key': 'value', 'label': 'Value'}], backend=dpg, sortable=True)
        assert dpg.get_item_theme(grid.tag) == shared
        assert dpg.get_item_configuration(grid.tag)['sortable'], 'Styling must not replace sortable native headers'
        grid.setRows([QtGridRow('a', ('Alpha', '10')), QtGridRow('b', ('Beta', '20'))])
        grid.setCurrentKey('a')
        grid.setRows([QtGridRow('a', ('Alpha', '11')), QtGridRow('b', ('Beta', '20'))])
        assert grid.selected == {'a'}
        # Job tables retain their centered, frozen noninteractive header and
        # logical row indices. Styling does not add hidden rows to other grids.
        jobs = QTableWidget(0, 2, parent=parent, backend=dpg)
        header, labels = style_job_table(jobs.tag, ['Job', 'Status'], 26)
        jobs.setRowCount(1)
        assert jobs.rowCount() == 1 and jobs.nativeRow(0) != header
        assert all(not dpg.get_item_configuration(item)['enabled'] for item in labels)
        assert dpg.get_item_configuration(jobs.tag)['freeze_rows'] == 1
        assert dpg.get_item_configuration(table.tag)['header_row']
        print('PASS: shared Schedule-style table palette/padding across editable, sortable, worksheet, '
              'dialog and conflict tables; centered Job headers and row/selection behavior preserved')
    finally:
        dpg.destroy_context()


if __name__ == '__main__':
    main()
