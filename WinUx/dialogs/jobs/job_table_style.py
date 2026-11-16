"""Shared presentation for the Job Manager and Job Schedule tables."""
from DearUIQt.backends import dpg
from DearUIQt.gui.palette import QtFusionPalette
from DearUIQt.modelview.themes import qt_item_view_theme


def _job_table_theme():
    return qt_item_view_theme(dpg)


def style_job_table(table, labels, header_height):
    """Add a frozen, centered presentation header outside managed data rows.

    Native ImGui headings are left-aligned. Full-width noninteractive controls
    center themselves during resize without measured-text layout callbacks.
    QTableWidget still owns the column definitions and all editable data rows.
    """
    dpg.configure_item(table, header_row=False, borders_innerV=False)
    dpg.bind_item_theme(table, _job_table_theme())
    cells = []
    with dpg.table_row(parent=table) as header:
        for label in labels:
            cells.append(dpg.add_button(
                label=label, width=-1, height=header_height, enabled=False))
    dpg.highlight_table_row(table, 0, QtFusionPalette.TABLE_HEADER)
    return header, cells
