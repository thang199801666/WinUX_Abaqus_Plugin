from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from WinUx.dialogs.folder_browser_style import BrowserListPalette, METRICS
from WinUx.dialogs.local_folder_form import FolderListView, LocalFolderDialog


class _Rect:
    def __init__(self, height):
        self._height = height

    def height(self):
        return self._height


class _Table:
    tag = "browser-table"
    _deleted = False


class _Backend:
    def __init__(self):
        self.cells = []
        self.cleared_cells = []
        self.rows = []

    def highlight_table_cell(self, tag, row, column, color):
        self.cells.append((tag, row, column, color))

    def unhighlight_table_cell(self, tag, row, column):
        self.cleared_cells.append((tag, row, column))

    def highlight_table_row(self, tag, row, color):
        self.rows.append((tag, row, color))




class _Bounds:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def isEmpty(self):
        return self.right <= self.left or self.bottom <= self.top

    def contains(self, point):
        x, y = point
        return self.left <= x < self.right and self.top <= y < self.bottom


class _Retained:
    def __init__(self, bounds):
        self._bounds = bounds

    def globalGeometry(self, clipped=True):
        return self._bounds


class _ListHitProbe:
    def __init__(self, result=True):
        self.calls = 0
        self.result = result

    def _row_pointer_clicked(self, point=None):
        self.calls += 1
        return self.result


class _RuntimeNoPopup:
    def hasActivePopupSurface(self, **_kwargs):
        return False


class ExplorerViewModeTests(unittest.TestCase):
    def test_list_mode_flows_down_then_across(self):
        view = FolderListView.__new__(FolderListView)
        view._values = [object()] * 25
        view.globalGeometry = lambda clipped=True: _Rect(METRICS.list_row_height * 8 + 2)
        rows, columns = FolderListView._list_flow_shape(view)
        self.assertEqual(rows, 8)
        self.assertEqual(columns, 4)
        # Logical index 9 therefore belongs to row 1 of the second column:
        # index = column * rows + row.
        self.assertEqual((9 % rows, 9 // rows), (1, 1))


    def test_small_icon_rows_have_vertical_clip_guard(self):
        details_content = METRICS.row_height - 2 * METRICS.table_cell_padding_y
        list_content = METRICS.list_row_height - 2 * METRICS.list_cell_padding_y
        self.assertGreaterEqual(details_content - METRICS.list_icon_size, 8)
        self.assertGreaterEqual(list_content - METRICS.list_icon_size, 8)

    def test_shell_icons_use_native_image_widget_not_clipped_drawlist(self):
        source = inspect.getsource(FolderListView.setItems)
        self.assertIn("QImageView(", source)
        self.assertNotIn("QPainter(icon_canvas).drawImage", source)

    def test_small_shell_icons_have_transparent_texture_guard(self):
        source = inspect.getsource(FolderListView.setItems)
        self.assertIn("icon_guard = 1 if icon_size == METRICS.list_icon_size else 0", source)
        self.assertIn("padding=icon_guard", source)
        self.assertIn("rendered_icon_size = icon_size + 2 * icon_guard", source)

    def test_list_mode_assigns_filename_width_before_reparent_clip(self):
        view = FolderListView.__new__(FolderListView)
        view.details_mode = False
        width = FolderListView._initial_name_width(view)
        self.assertGreater(width, 32)
        self.assertEqual(width, FolderListView._list_name_width())

        view.details_mode = True
        self.assertGreater(FolderListView._initial_name_width(view), 32)

    def test_list_selection_highlights_only_its_cell(self):
        view = FolderListView.__new__(FolderListView)
        view._details_table = _Table()
        view.details_mode = False
        view._visual_positions = {"file": (2, 3)}
        view._hovered_row_key = None
        view._row_enabled = {"file": True}
        view._state = SimpleNamespace(selected={"file"}, current="file", anchor="file")
        view._has_focus = True
        view.backend = _Backend()

        FolderListView._paint_row_background(view, "file")
        self.assertEqual(
            view.backend.cells[-1],
            ("browser-table", 2, 3, BrowserListPalette.SELECTED),
        )
        self.assertEqual(view.backend.rows, [])



    def test_modal_view_mode_button_has_priority_over_list_hitbox(self):
        dialog = LocalFolderDialog.__new__(LocalFolderDialog)
        dialog.list_view_button = "list-button"
        dialog.details_view_button = "details-button"
        changed = []
        dialog._change_view = changed.append

        bounds = {
            "list-button": _Bounds(620, 78, 646, 104),
            "details-button": _Bounds(648, 78, 674, 104),
        }
        retained = lambda item: _Retained(bounds[item])
        details_point = SimpleNamespace(x=lambda: 660, y=lambda: 90)

        with patch("WinUx.dialogs.local_folder_form.QRetainedItem", side_effect=retained):
            claimed = LocalFolderDialog._view_mode_pointer_hit(dialog, details_point)

        self.assertTrue(claimed)
        self.assertEqual(changed, ["Details"])

    def test_view_button_opens_menu_instead_of_forcing_list_mode(self):
        dialog = LocalFolderDialog.__new__(LocalFolderDialog)
        dialog.list_view_button = "list-button"
        dialog.details_view_button = "details-button"
        opened = []
        dialog._show_view_options_menu = lambda: opened.append(True) or True
        dialog._change_view = lambda mode: self.fail("View menu button must not force %s" % mode)
        bounds = {
            "list-button": _Bounds(620, 78, 646, 104),
            "details-button": _Bounds(648, 78, 674, 104),
        }
        retained = lambda item: _Retained(bounds[item])
        point = SimpleNamespace(x=lambda: 632, y=lambda: 90)
        with patch("WinUx.dialogs.local_folder_form.QRetainedItem", side_effect=retained):
            claimed = LocalFolderDialog._view_mode_pointer_hit(dialog, point)
        self.assertTrue(claimed)
        self.assertEqual(opened, [True])

    def test_modal_pointer_router_never_claims_toolbar_pixels(self):
        dialog = LocalFolderDialog.__new__(LocalFolderDialog)
        dialog.winfo_exists = lambda: True
        dialog.isVisible = lambda: True
        dialog._folder_menu_is_open = lambda: False
        dialog._folder_menu_action_pending = False
        dialog._rename_path = None
        dialog._rename_after_load = None
        dialog.tag = "dialog"
        dialog.folder_region = "folder-region"
        dialog.places = "places"
        dialog.listbox = _ListHitProbe(result=True)

        bounds = {
            "folder-region": _Bounds(185, 120, 700, 410),
            "places": _Bounds(35, 120, 185, 410),
        }
        retained = lambda item: _Retained(bounds[item])
        toolbar_point = SimpleNamespace(x=lambda: 655, y=lambda: 92)

        with patch("WinUx.dialogs.local_folder_form.QApplication.instance", return_value=None), \
             patch("WinUx.dialogs.local_folder_form.QGuiRuntime", return_value=_RuntimeNoPopup()), \
             patch("WinUx.dialogs.local_folder_form.QRetainedItem", side_effect=retained):
            claimed = LocalFolderDialog._selector_pointer_hit(dialog, toolbar_point)

        self.assertFalse(claimed)
        self.assertEqual(dialog.listbox.calls, 0)

    def test_modal_pointer_router_still_routes_folder_view_pixels(self):
        dialog = LocalFolderDialog.__new__(LocalFolderDialog)
        dialog.winfo_exists = lambda: True
        dialog.isVisible = lambda: True
        dialog._folder_menu_is_open = lambda: False
        dialog._folder_menu_action_pending = False
        dialog._rename_path = None
        dialog._rename_after_load = None
        dialog.tag = "dialog"
        dialog.folder_region = "folder-region"
        dialog.places = "places"
        dialog.listbox = _ListHitProbe(result=True)

        bounds = {
            "folder-region": _Bounds(185, 120, 700, 410),
            "places": _Bounds(35, 120, 185, 410),
        }
        retained = lambda item: _Retained(bounds[item])
        list_point = SimpleNamespace(x=lambda: 420, y=lambda: 220)

        with patch("WinUx.dialogs.local_folder_form.QApplication.instance", return_value=None), \
             patch("WinUx.dialogs.local_folder_form.QGuiRuntime", return_value=_RuntimeNoPopup()), \
             patch("WinUx.dialogs.local_folder_form.QRetainedItem", side_effect=retained):
            claimed = LocalFolderDialog._selector_pointer_hit(dialog, list_point)

        self.assertTrue(claimed)
        self.assertEqual(dialog.listbox.calls, 1)


    def test_explorer_view_menu_exposes_all_eight_modes(self):
        self.assertEqual(
            FolderListView.VIEW_MODES,
            (
                "Extra large icons", "Large icons", "Medium icons", "Small icons",
                "List", "Details", "Tiles", "Content",
            ),
        )

    def test_grid_modes_flow_across_then_down(self):
        view = FolderListView.__new__(FolderListView)
        view.details_mode = False
        view.view_mode_name = "Medium icons"
        view._values = [object()] * 17

        class _GridRect:
            def width(self):
                return 600

        view.globalGeometry = lambda clipped=True: _GridRect()
        rows, columns = FolderListView._mode_flow_shape(view)
        self.assertEqual(columns, 4)
        self.assertEqual(rows, 5)

    def test_content_mode_is_single_vertical_column(self):
        view = FolderListView.__new__(FolderListView)
        view.details_mode = False
        view.view_mode_name = "Content"
        view._values = [object()] * 9
        rows, columns = FolderListView._mode_flow_shape(view)
        self.assertEqual((rows, columns), (9, 1))

    def test_set_view_mode_keeps_details_compatibility_flag(self):
        view = FolderListView.__new__(FolderListView)
        FolderListView.setViewMode(view, "Large icons")
        self.assertEqual(view.viewMode(), "Large icons")
        self.assertFalse(view.details_mode)
        FolderListView.setViewMode(view, "Details")
        self.assertTrue(view.details_mode)

    def test_details_selection_still_highlights_full_row(self):
        view = FolderListView.__new__(FolderListView)
        view._details_table = _Table()
        view.details_mode = True
        view._row_index = {"file": 4}
        view._hovered_row_key = "file"
        view._row_enabled = {"file": True}
        view._state = SimpleNamespace(selected={"file"}, current="file", anchor="file")
        view._has_focus = True
        view.backend = _Backend()

        FolderListView._paint_row_background(view, "file")
        self.assertEqual(
            view.backend.rows[-1],
            ("browser-table", 4, BrowserListPalette.SELECTED_HOVER),
        )
        self.assertEqual(view.backend.cells, [])


if __name__ == "__main__":
    unittest.main()
