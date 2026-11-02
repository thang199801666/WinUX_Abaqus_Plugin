"""Render the empty folder header and verify the separators' painted pixels.

Run with: abaqus python tests/test_file_selector_header_render_ui.py
"""
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))

from DearUIQt.backends import dpg
from PIL import Image
from WinUx.dialogs.local_folder_form import FolderDetailsTable, FolderListView
from WinUx.dialogs.folder_browser_style import browser_details_theme, BrowserListPalette, METRICS


def main():
    dpg.create_context()
    table = None
    try:
        with dpg.window(label='Folder header render test', width=740, height=360) as window:
            table = FolderDetailsTable(
                rows=0, columns=4, parent=window, backend=dpg,
                header_row=False, height=280, scroll_y=True,
                freeze_rows=1, grid_lines=False, resizable=True,
                borders_outerH=False, borders_outerV=False)
            table.setTheme(browser_details_theme())
            table.setHorizontalHeaderLabels(['Name', 'Size', 'Type', 'Date modified'])
            for column, width in enumerate((280, 100, 120, 150)):
                table.setColumnWidth(column, width)
            table.setColumnStretch(0, 1.0)
            view = FolderListView.__new__(FolderListView)
            view.backend = dpg
            view.sort_column, view.sort_ascending = 0, True
            view._install_centered_details_header(
                table, ['Name', 'Size', 'Type', 'Date modified'])

        dpg.create_viewport(title='Folder header render test', width=760, height=400)
        dpg.setup_dearpygui()
        dpg.set_primary_window(window, True)
        dpg.show_viewport()

        def verify(label):
            for _ in range(12):
                dpg.render_dearpygui_frame()
                time.sleep(.02)
            target = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
            screenshot = target / ('folder_header_' + label + '.png')
            dpg.output_frame_buffer(str(screenshot))
            for _ in range(4):
                dpg.render_dearpygui_frame()
            frame = Image.open(screenshot).convert('RGB')
            for index, line in enumerate(view._details_header_separators):
                x, y = dpg.get_item_rect_min(line)
                stroke_x = METRICS.details_cell_padding_x
                next_x = dpg.get_item_rect_min(view._details_header_cells[index + 1])[0]
                boundary = next_x - METRICS.details_cell_padding_x
                assert abs(x + stroke_x - (boundary - 1)) <= 1, (
                    label, index, 'misaligned separator', x + stroke_x, boundary)
                width, height = dpg.get_item_rect_size(line)
                rect = tuple(round(value) for value in (x, y, x + width, y + height))
                image = frame.crop(rect)
                expected = BrowserListPalette.HEADER_BORDER[:3]
                painted = sum(
                    max(abs(a - b) for a, b in zip(image.getpixel((stroke_x, y))[:3], expected)) < 12
                    for y in range(3, image.height - 3))
                assert painted >= image.height - 8, (label, line, rect, painted, expected)
            print('PASS: three visible 1px header rules (%s); %s' % (label, screenshot), flush=True)

        verify('empty')
        first_x = dpg.get_item_rect_min(view._details_header_separators[0])[0]
        dpg.configure_item(table.tag, width=600)
        verify('resized')
        assert dpg.get_item_rect_min(view._details_header_separators[0])[0] != first_x
        header_y = dpg.get_item_rect_min(view._details_header_separators[0])[1]
        for index in range(30):
            with dpg.table_row(parent=table.tag):
                for value in ('Folder %d' % index, '', 'File folder', ''):
                    dpg.add_text(value)
        for _ in range(4):
            dpg.render_dearpygui_frame()
        dpg.set_y_scroll(table.tag, 100)
        verify('scrolled')
        assert dpg.get_y_scroll(table.tag) > 0
        assert dpg.get_item_rect_min(view._details_header_separators[0])[1] == header_y
        separators = list(view._details_header_separators)
        table.delete()
        table = None
        assert all(not dpg.does_item_exist(line) for line in separators)
    finally:
        if table is not None:
            table.delete()
        dpg.destroy_context()


if __name__ == '__main__':
    main()
