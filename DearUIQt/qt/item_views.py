"""Compatibility facade for Qt/Fusion-like Dear ImGui item views.

Implementation is split into focused modules so model/state, theming, grid and
list concerns can be reused or tested independently. Existing imports from
``DearUIQt.qt.item_views`` remains the canonical import path.
"""
from __future__ import annotations

from .item_models import (
    QtGridColumn, QtGridRow, QtListItem, QtSelectionMode, QtItemViewState,
)
from .item_themes import (
    qt_item_view_theme, qt_item_row_theme, qt_item_text_theme,
    qt_context_menu_theme, qt_list_view_theme,
)
from .item_grid import ImGuiHeaderView, QHeaderView, QtDataGridView, ImGuiDataGridView, QTableView
from .item_list import QtListView, ImGuiListView, QListView
from .tree import QTreeItem, QTreeView

ImGuiItemViewState = QtItemViewState

__all__ = [
    "QtGridColumn", "QtGridRow", "QtListItem", "QtSelectionMode", "QtItemViewState",
    "QtDataGridView", "QtListView", "ImGuiItemViewState",
    "ImGuiDataGridView", "ImGuiListView", "ImGuiHeaderView", "QHeaderView",
    "QTableView", "QListView", "QTreeItem", "QTreeView", "qt_item_view_theme", "qt_item_row_theme",
    "qt_item_text_theme", "qt_context_menu_theme", "qt_list_view_theme",
]
