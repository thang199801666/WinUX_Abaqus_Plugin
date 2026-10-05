"""Exercise real browser widgets, asynchronous listings and folder selection."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import WinUx
import dearpygui.dearpygui as dpg
from WinUx.dialogs.local_folder_form import LocalFolderDialog
from WinUx.components.toolbar import ResourceTextures
from WinUx.platform.windows_icons import WindowsIconRegistry
from WinUx.dialogs.floating_runtime import configure_context


class View:
    def __init__(self):
        self.queue = []
        self.lock = threading.Lock()

    def after(self, delay, callback, *args):
        with self.lock:
            self.queue.append((callback, args))

    def drain(self):
        with self.lock:
            queued, self.queue = self.queue, []
        for callback, args in queued:
            callback(*args)


class FolderBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("Beta", "Alpha", "Empty"):
            (self.root / name).mkdir()
        (self.root / "Alpha" / "Nested").mkdir()
        (self.root / "file.txt").write_text("not a folder", encoding="utf-8")
        self.view = View()
        self.results = []
        dpg.create_context()
        configure_context(self.view)
        dpg.create_viewport(title="WinUx folder browser check", width=850, height=600)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        with patch("tkinter.Tk", side_effect=AssertionError("Unexpected Tk root")):
            self.dialog = LocalFolderDialog(self.view, self.root, self.results.append)
        self.wait_listing()

    def tearDown(self):
        self.dialog.destroy()
        self.view.drain()
        ResourceTextures.reset()
        WindowsIconRegistry.reset()
        dpg.destroy_context()
        self.temp.cleanup()

    def frame(self):
        self.view.drain()
        dpg.render_dearpygui_frame()
        dpg.run_callbacks(dpg.get_callback_queue())

    def wait_listing(self):
        deadline = time.monotonic() + 5
        while dpg.get_value(self.dialog.status) == "Loading...":
            self.frame()
            if time.monotonic() > deadline:
                self.fail("Directory listing did not finish")
            time.sleep(0.005)
        for _ in range(3):
            self.frame()

    def test_listing_has_folder_icons_and_excludes_files(self):
        self.assertEqual([item.text for item in self.dialog.listbox._values],
                         ["Alpha", "Beta", "Empty"])
        self.assertEqual(dpg.get_value(self.dialog.folder_edit), str(self.root))
        first = self.dialog.listbox.items[str(self.root / "Alpha")]
        parent = dpg.get_item_info(first)["parent"]
        self.assertEqual(dpg.get_item_info(parent)["type"], "mvAppItemType::mvGroup")
        self.assertGreater(dpg.get_item_rect_size(first)[0], 100,
                           (dpg.get_item_state(first), dpg.get_item_configuration(first)))
        self.assertFalse(dpg.get_item_configuration(self.dialog.back_button)["enabled"])

    def test_navigation_history_double_click_and_up(self):
        self.dialog._enter_key(str(self.root / "Alpha"))
        self.wait_listing()
        self.assertEqual(self.dialog._current_path, str(self.root / "Alpha"))
        self.dialog._go_back()
        self.wait_listing()
        self.assertEqual(self.dialog._current_path, str(self.root))
        self.dialog._go_forward()
        self.wait_listing()
        self.assertEqual(self.dialog._current_path, str(self.root / "Alpha"))
        self.dialog._go_up()
        self.wait_listing()
        self.assertEqual(self.dialog._current_path, str(self.root))
        self.assertFalse(dpg.get_item_configuration(self.dialog.forward_button)["enabled"])

    def test_filter_and_child_selection(self):
        dpg.set_value(self.dialog.filter_edit, "ALP")
        self.dialog._filter_entries()
        self.assertEqual([item.text for item in self.dialog.listbox._values], ["Alpha"])
        self.dialog.listbox.setCurrentKey(str(self.root / "Alpha"), select=True)
        self.assertEqual(dpg.get_value(self.dialog.folder_edit), str(self.root / "Alpha"))
        self.dialog._select_folder()
        self.assertEqual(self.results, [str(self.root / "Alpha")])

    def test_quick_access_callback_accepts_native_three_argument_dispatch(self):
        self.dialog._enter_key(str(self.root / "Alpha"))
        self.wait_listing()
        home = self.dialog.place_buttons["Home"]
        with patch.object(self.dialog, "_navigate", return_value=True) as navigate:
            dpg.get_item_configuration(home)["callback"](home, True, None)
        navigate.assert_called_once_with(str(Path.home()))

    def test_native_header_sort_preserves_selection_and_visible_rows(self):
        key = str(self.root / "Alpha")
        self.dialog.listbox.setCurrentKey(key, select=True)
        column = next(tag for tag, index in self.dialog.listbox._column_keys.items() if index == 0)
        table = self.dialog.listbox.table
        dpg.get_item_configuration(table)["callback"](table, [[column, -1]], None)
        for _ in range(5):
            self.frame()
        self.assertEqual([item.text for item in self.dialog.listbox._values],
                         ["Empty", "Beta", "Alpha"])
        self.assertEqual(self.dialog.listbox.currentData(), key)
        self.assertEqual(dpg.get_value(self.dialog.folder_edit), key)
        first = self.dialog.listbox.items[str(self.root / "Empty")]
        self.assertTrue(dpg.get_item_state(first)["visible"])
        self.assertGreater(dpg.get_item_rect_size(first)[0], 100)

        self.dialog._folder_mtimes = {
            str(self.root / "Alpha"): 2000,
            str(self.root / "Beta"): 1000,
            str(self.root / "Empty"): 3000,
        }
        column = next(tag for tag, index in self.dialog.listbox._column_keys.items() if index == 1)
        table = self.dialog.listbox.table
        dpg.get_item_configuration(table)["callback"](table, [[column, -1]], None)
        for _ in range(5):
            self.frame()
        self.assertEqual([item.text for item in self.dialog.listbox._values],
                         ["Empty", "Alpha", "Beta"])

    @unittest.skipUnless(os.name == "nt", "Windows Shell integration")
    def test_shell_icon_is_nontransparent_and_cached_in_current_context(self):
        image = WindowsIconRegistry.read_path_image(self.root)
        self.assertIsNotNone(image)
        self.assertIsNotNone(image.getchannel("A").getbbox())
        texture = WindowsIconRegistry.get_path_icon(self.root, image)
        self.assertEqual(WindowsIconRegistry.get_path_icon(self.root), texture)
        self.assertTrue(dpg.does_item_exist(texture))
        stock = WindowsIconRegistry.get_stock_icon(94)
        self.assertEqual(WindowsIconRegistry.get_stock_icon(94), stock)
        self.assertNotEqual(stock, WindowsIconRegistry.get_icon(is_dir=True))

    def test_empty_folder_keeps_current_folder_selectable(self):
        self.dialog._enter_key(str(self.root / "Empty"))
        self.wait_listing()
        self.assertEqual(self.dialog.listbox._values, [])
        self.assertEqual(self.dialog.listbox.empty_text, "This folder is empty.")
        self.dialog._select_folder()
        self.assertEqual(self.results, [str(self.root / "Empty")])

    def test_address_edit_escape_and_native_close_have_distinct_behavior(self):
        self.dialog.address.begin_edit()
        for _ in range(3):
            self.frame()
        self.assertTrue(dpg.is_item_shown(self.dialog.path_edit))
        self.assertFalse(dpg.is_item_shown(self.dialog.breadcrumbs))
        dpg.set_value(self.dialog.path_edit, "invalid draft")
        self.dialog._close_from_escape()
        self.assertTrue(self.dialog.winfo_exists())
        self.assertFalse(self.results)
        self.assertEqual(dpg.get_value(self.dialog.path_edit), str(self.root))
        self.assertTrue(dpg.is_item_shown(self.dialog.breadcrumbs))
        self.dialog.address.begin_edit()
        self.dialog._close_from_native()
        self.dialog._close_from_native()
        self.assertEqual(self.results, [None])

    def test_breadcrumb_click_navigates_parent(self):
        self.dialog._enter_key(str(self.root / "Alpha"))
        self.wait_listing()
        button = next(tag for tag in dpg.get_item_children(self.dialog.breadcrumbs, 1)
                      if dpg.get_item_configuration(tag).get("label") == self.root.name)
        dpg.get_item_configuration(button)["callback"](button, None, None)
        self.wait_listing()
        self.assertEqual(self.dialog._current_path, str(self.root))

    def test_list_mode_survives_filter_refresh(self):
        self.dialog._change_view("List")
        self.assertFalse(dpg.get_item_configuration(self.dialog.listbox.table)["header_row"])
        self.assertTrue(all(not dpg.get_item_configuration(tag)["show"]
                            for tag in self.dialog.listbox.detail_columns))
        dpg.set_value(self.dialog.filter_edit, "Al")
        self.dialog._filter_entries()
        for _ in range(3):
            self.frame()
        self.assertTrue(all(not dpg.get_item_configuration(tag)["show"]
                            for tag in self.dialog.listbox.detail_columns))
        self.assertEqual([item.text for item in self.dialog.listbox._values], ["Alpha"])
        self.assertFalse(dpg.get_item_configuration(self.dialog.listbox.table)["header_row"])
        self.dialog._change_view("Details")
        self.assertEqual(len(self.dialog.listbox.detail_columns), 2)

    def wait_create(self):
        deadline = time.monotonic() + 5
        while self.dialog._creating_folder or dpg.get_value(self.dialog.status) == "Loading...":
            self.frame()
            if time.monotonic() > deadline:
                self.fail("Folder creation did not finish")
            time.sleep(0.005)
        for _ in range(3):
            self.frame()

    def test_new_folder_is_created_and_selected_without_closing_dialog(self):
        self.dialog._show_new_folder()
        dpg.set_value(self.dialog.new_folder_edit, "Created folder")
        self.dialog._create_folder()
        self.wait_create()
        created = self.root / "Created folder"
        self.assertTrue(created.is_dir())
        self.assertEqual(self.dialog.listbox.currentData(), str(created))
        self.assertEqual(dpg.get_value(self.dialog.folder_edit), str(created))
        self.assertFalse(dpg.is_item_shown(self.dialog.new_folder_row))
        self.assertTrue(self.dialog.winfo_exists())
        self.assertFalse(self.results)

    def test_new_folder_rejects_path_and_existing_directory(self):
        self.dialog._show_new_folder()
        dpg.set_value(self.dialog.new_folder_edit, "../outside")
        self.dialog._create_folder()
        self.assertFalse(self.dialog._creating_folder)
        self.assertIn("without path separators", dpg.get_value(self.dialog.status))
        dpg.set_value(self.dialog.new_folder_edit, "Alpha")
        self.dialog._create_folder()
        self.wait_create()
        self.assertIn("Could not create folder", dpg.get_value(self.dialog.status))
        self.assertTrue((self.root / "Alpha" / "Nested").is_dir())
        self.dialog._close_from_escape()
        self.assertTrue(self.dialog.winfo_exists())
        self.assertFalse(dpg.is_item_shown(self.dialog.new_folder_row))

    def test_sidebar_groups_can_collapse_and_expand(self):
        body = self.dialog.quick_group
        groups = dpg.get_item_children(self.dialog.places, 1)
        header = groups[groups.index(body) - 1]
        toggle = dpg.get_item_children(header, 1)[0]
        callback = dpg.get_item_configuration(toggle)["callback"]
        callback(toggle, None, None)
        self.assertFalse(dpg.is_item_shown(body))
        callback(toggle, None, None)
        self.assertTrue(dpg.is_item_shown(body))

    def test_browser_keyboard_shortcuts_dispatch_to_address_and_new_folder(self):
        with patch.object(dpg, "is_key_down", side_effect=lambda key: key == dpg.mvKey_LControl):
            self.dialog._browser_key(None, dpg.mvKey_L)
        self.assertTrue(self.dialog.address.editing)
        with patch.object(dpg, "is_key_down", side_effect=lambda key: key in
                          (dpg.mvKey_LControl, dpg.mvKey_LShift)):
            self.dialog._browser_key(None, dpg.mvKey_N)
        self.assertTrue(dpg.is_item_shown(self.dialog.new_folder_row))
        self.assertFalse(self.dialog.address.editing)

    def test_new_folder_editor_fits_at_minimum_window_size(self):
        dpg.configure_item(self.dialog.tag, width=620, height=400)
        self.dialog._show_new_folder()
        for _ in range(5):
            self.frame()
        self.assertTrue(dpg.get_item_state(self.dialog.create_folder_button)["visible"])
        editor_pos = dpg.get_item_rect_min(self.dialog.folder_edit)
        editor_size = dpg.get_item_rect_size(self.dialog.folder_edit)
        self.assertLess(editor_pos[1] + editor_size[1],
                        dpg.get_item_rect_min(self.dialog._default_button)[1])

    def test_typed_relative_path_and_invalid_selection(self):
        dpg.set_value(self.dialog.folder_edit, "missing")
        self.dialog._select_folder()
        self.assertTrue(self.dialog.winfo_exists())
        self.assertFalse(self.results)
        dpg.set_value(self.dialog.path_edit, "Alpha")
        self.dialog._navigate_typed()
        self.wait_listing()
        dpg.set_value(self.dialog.folder_edit, "Nested")
        self.dialog._select_folder()
        self.assertEqual(self.results, [str(self.root / "Alpha" / "Nested")])

    def test_stale_listing_and_cancel_are_safe(self):
        original = list(self.dialog.listbox._values)
        self.dialog._apply_entries(self.dialog._generation - 1, str(self.root), [], None)
        self.assertEqual(self.dialog.listbox._values, original)
        self.dialog.finish(None)
        self.dialog.finish(str(self.root))
        self.assertEqual(self.results, [None])

    def test_minimum_resize_keeps_selection_and_buttons_visible(self):
        dpg.configure_item(self.dialog.tag, width=620, height=400)
        for _ in range(5):
            self.frame()
        folder_pos = dpg.get_item_rect_min(self.dialog.folder_edit)
        folder_size = dpg.get_item_rect_size(self.dialog.folder_edit)
        footer_pos = dpg.get_item_rect_min(self.dialog._default_button)
        self.assertLess(folder_pos[1] + folder_size[1], footer_pos[1])
        self.assertGreater(dpg.get_item_rect_size(self.dialog.listbox.tag)[1], 100)
        screenshot = os.environ.get("WINUX_FOLDER_BROWSER_SCREENSHOT")
        if screenshot:
            dpg.output_frame_buffer(screenshot)
            for _ in range(4):
                self.frame()


if __name__ == "__main__":
    unittest.main()
