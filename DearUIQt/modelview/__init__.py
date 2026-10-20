"""Qt model/view-style public namespace with canonical implementations."""
from .._lazy import resolve, namespace_dir
_EXPORTS = {
    "QtGridColumn": ".models", "QtGridRow": ".models",
    "QtListItem": ".models", "QtSelectionMode": ".models",
    "QtItemViewState": ".models", "QAbstractItemView": ".base", "QHeaderView": ".table",
    "QtDataGridView": ".table", "QTableView": ".table",
    "QTableWidget": ".table_widget", "QTableWidgetItem": ".table_widget",
    "QtListView": ".list", "QListView": ".list",
    "QListWidget": ".list_widget", "QListWidgetItem": ".list_widget",
    "QTreeItem": ".tree", "QTreeView": ".tree",
    "QTreeWidget": ".tree_widget", "QTreeWidgetItem": ".tree_widget",
    "QAbstractItemDelegate": ".delegates", "QStyledItemDelegate": ".delegates",
    "QStandardItem": "..gui.standard_item_model", "QStandardItemModel": "..gui.standard_item_model",
    "QModelIndex": "..core.item_model", "QPersistentModelIndex": "..core.item_model",
    "QAbstractItemModel": "..core.item_model", "QAbstractTableModel": "..core.item_model",
    "QAbstractListModel": "..core.item_model", "QItemSelectionRange": "..core.item_model",
    "QItemSelection": "..core.item_model", "QItemSelectionModel": "..core.item_model",
    "qt_item_text_theme": ".themes", "qt_item_row_theme": ".themes",
    "qt_item_view_theme": ".themes", "qt_context_menu_theme": ".themes",
    "qt_list_view_theme": ".themes",
    "VirtualRowWindow": ".virtual_table", "compute_virtual_window": ".virtual_table",
    "ReadOnlyTableViewport": ".virtual_table", "LogicalTableScrollBridge": ".virtual_table",
    "ViewResourceSnapshot": ".diagnostics", "capture_view_resources": ".diagnostics",
    "ViewMemorySample": ".diagnostics", "ViewMemoryDelta": ".diagnostics",
    "capture_view_memory": ".diagnostics", "compare_view_memory": ".diagnostics",
}
__all__ = list(_EXPORTS)
def __getattr__(name): return resolve(globals(), __name__, _EXPORTS, name)
def __dir__(): return namespace_dir(globals(), _EXPORTS)
