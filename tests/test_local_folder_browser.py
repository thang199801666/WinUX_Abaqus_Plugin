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
from DearUIQt.widgets import QApplication
from WinUx.dialogs.local_folder_form import LocalFolderDialog
from WinUx.ui.components.toolbar import ResourceTextures
from WinUx.platform.windows_icons import WindowsIconRegistry
from WinUx.dialogs.floating_runtime import configure_context
from DearUIQt.qt.scroller import dpg_window_rect


class View:
    def __init__(self):
        self.queue = []
        self.lock = threading.Lock()

    def after(self, delay, callback, *args):
        with self.lock:
            self.queue.append((time.monotonic() + max(0, delay) / 1000.0, callback, args))

    def drain(self):
        with self.lock:
            now = time.monotonic()
            queued = [job for job in self.queue if job[0] <= now]
            self.queue = [job for job in self.queue if job[0] > now]
        for _, callback, args in queued:
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
        # Production hosts (WinUx/view.py) always run with a QApplication;
        # selector behaviors like frame-count pointer transactions, clipboard
        # access and popup/modality ownership assume it exists.
        self.application = QApplication(after=self.view.after)
        dpg.create_viewport(title="WinUx folder browser check", width=850, height=600)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        with patch("tkinter.Tk", side_effect=AssertionError("Unexpected Tk root")):
            self.dialog = LocalFolderDialog(self.view, self.root, self.results.append)
        self.wait_listing()

    def tearDown(self):
        self.dialog.destroy()
        self.view.drain()
        self.application.delete()
        ResourceTextures.reset()
        WindowsIconRegistry.reset()
        dpg.destroy_context()
        self.temp.cleanup()

    def frame(self):
        self.view.drain()
        dpg.render_dearpygui_frame()
        dpg.run_callbacks(dpg.get_callback_queue())
        time.sleep(0.005)

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

    def test_sidebar_rows_have_visible_full_width_hit_targets(self):
        tree = self.dialog._places_tree
        self.assertEqual(tree.topLevelItemCount(), 2)
        self.assertGreater(self.dialog.drive_group.childCount(), 0)
        for root in (self.dialog.quick_group, self.dialog.drive_group):
            self.assertTrue(root.isExpanded())
            self.assertNotIn(root, tree._rendered, 'Qt Places sidebar should not show Explorer section headers')
            for item in (root.child(0),):
                target = tree.nativeItem(item)
                state = dpg.get_item_state(target)
                self.assertTrue(state['visible'], (item.text(0), state))
                self.assertGreater(state['rect_size'][0], 100, (item.text(0), state))
                self.assertEqual(dpg.get_item_configuration(target)['width'], 0)
        # Collapsing/rebuilding must not restore the negative-width rows.
        self.dialog.drive_group.setExpanded(False)
        self.dialog.drive_group.setExpanded(True)
        for _ in range(3):
            self.frame()
        target = tree.nativeItem(self.dialog.drive_group.child(0))
        self.assertGreater(dpg.get_item_rect_size(target)[0], 100)
        # Exercise the same native selectable callback used by pointer dispatch
        # without navigating/enumerating a potentially offline mapped drive.
        with patch.object(self.dialog, '_place_clicked') as clicked:
            item = self.dialog.drive_group.child(0)
            target = tree.nativeItem(item)
            options = dpg.get_item_configuration(target)
            options['callback'](target, True, options['user_data'])
            self.view.drain()
            self.assertIs(tree.currentItem(), item)
            clicked.assert_called_once()
        # Navigation remains deferred until the pointer release boundary. Test
        # the dispatch contract explicitly rather than depending on desktop
        # foreground ownership in unattended GUI sessions.
        with patch.object(self.dialog, '_navigate') as navigate, \
                patch.object(self.dialog, '_pointer_transaction_finished', return_value=True):
            home = self.dialog.place_buttons['Home']
            options = dpg.get_item_configuration(home)
            options['callback'](home, True, options['user_data'])
            navigate.assert_not_called()
            self.dialog._commit_place_navigation()
            navigate.assert_called_once_with(str(Path.home()))

    def test_sidebar_has_compact_qt_icon_and_label_geometry(self):
        tree = self.dialog._places_tree
        for item, expected_text_x, expected_icon_x in (
                (self.dialog.quick_group.child(0), 28, 5),
                (self.dialog.drive_group.child(0), 28, 5)):
            visual = tree._rendered[item]
            overlay_state = dpg.get_item_state(visual['overlay'])
            hit_state = dpg.get_item_state(visual['selectable'])
            self.assertTrue(overlay_state['visible'], (item.text(0), overlay_state))
            self.assertEqual(overlay_state['rect_min'], hit_state['rect_min'],
                             'Icon/text layer must overlap the native row, not flow below it')
            label = dpg.get_item_configuration(visual['text'])
            self.assertEqual(label['text'], item.text(0))
            self.assertEqual(label['size'], 13)
            self.assertEqual(label['pos'][0], expected_text_x)
            self.assertEqual(dpg.get_item_configuration(visual['selectable'])['label'], '')
            if expected_icon_x is not None:
                icon = dpg.get_item_configuration(visual['icon'])
                self.assertEqual(icon['pmin'], [expected_icon_x, 2])
                self.assertEqual(icon['pmax'], [expected_icon_x + 16, 18])
                self.assertTrue(dpg.does_item_exist(icon['texture_tag']))
        # Asynchronous drive display-name refresh must update the painted
        # caption rather than reintroducing a second native text target.
        drive = self.dialog.drive_group.child(0)
        self.dialog._set_place_label(drive, 'Test drive (C:)')
        visual = tree._rendered[drive]
        self.assertEqual(dpg.get_item_configuration(visual['text'])['text'],
                         self.dialog._elide_sidebar_label('Test drive (C:)'))

    def test_compact_qt_selector_layout_and_size_column(self):
        dialog = self.dialog
        self.assertFalse(dialog.has_footer, 'Actions should align beside the filename/filter rows')
        self.assertFalse(dpg.is_item_shown(dialog.search_shell))
        table = dialog.listbox._details_table
        self.assertEqual(table.columnCount(), 4)
        self.assertEqual(table._headers, ['Name', 'Size', 'Type', 'Date Modified'])
        self.assertEqual(dialog.listbox._column_keys[table.nativeColumn(1)], 2)
        self.assertEqual(dialog.listbox._column_keys[table.nativeColumn(3)], 1)
        self.assertEqual(dpg.get_item_parent(dialog._accept_button), dialog._selection_grid.cell(0, 2).tag)
        self.assertEqual(dpg.get_item_parent(dialog._reject_button), dialog._selection_grid.cell(1, 2).tag)
        for row, item in enumerate(dialog.listbox._values):
            size = table.item(row, 1).text()
            if dialog._entry_types[item.key] == 'Folder':
                self.assertEqual(size, '')
            elif item.text == 'file.txt':
                self.assertEqual(size, '12 bytes')
        self.assertEqual(dialog.listbox._format_size(2191), '2.14 KiB')
        self.assertFalse(dpg.is_item_shown(dialog.status), 'Normal item counts must not reserve a footer')
        for control in (dialog.control_wrapper(dialog._accept_button),
                        dialog.control_wrapper(dialog._reject_button),
                        dialog._details_view_control):
            theme = control.theme()
            self.assertIsNotNone(theme)
            control._refresh_style()
            self.assertEqual(dpg.get_item_info(control.tag)['theme'], theme,
                             'Passive focus styling must preserve selector-specific chrome')

    def test_folder_list_and_address_use_windows_shell_folder_icon(self):
        from WinUx.dialogs.folder_browser_style import folder_item_texture, address_location_texture
        native_folder = WindowsIconRegistry.get_icon(is_dir=True)
        self.assertEqual(folder_item_texture(), native_folder)
        self.assertEqual(folder_item_texture(size=18), native_folder)
        self.assertEqual(address_location_texture(str(self.root)), native_folder)
        for item in self.dialog.listbox._values:
            if self.dialog._entry_types[item.key] == 'Folder':
                image = self.dialog.listbox.icons[item.key]
                self.assertEqual(dpg.get_item_configuration(image)['texture_tag'], native_folder)

    def test_qt_location_field_remains_editable_and_offers_parent_locations(self):
        address = self.dialog.address
        self.assertFalse(dpg.is_item_shown(address.breadcrumbs))
        self.assertTrue(dpg.is_item_shown(address.editor))
        address.begin_edit()
        address._editor_control.setText('typed path not committed')
        address.refresh(force=True)
        self.assertEqual(address._editor_control.text(), 'typed path not committed')
        address.end_edit()
        self.assertTrue(dpg.is_item_shown(address.editor))
        self.assertEqual(address._editor_control.text(), self.dialog._current_path)
        theme = address._editor_control.theme()
        address._editor_control._refresh_style()
        self.assertEqual(dpg.get_item_info(address.editor)['theme'], theme,
                         'Focus styling must not reintroduce a nested input border')
        with patch.object(address._locations, 'popup'), \
                patch.object(address._locations, 'setActions') as set_actions:
            address._show_locations()
            paths = [entry['action'] for entry in set_actions.call_args.args[0]]
            self.assertIn(str(self.root.parent), paths)
            self.assertIn(self.dialog._current_path, paths)
            self.assertEqual(len(paths), len(set(paths)))
        with patch.object(self.view, 'after') as after:
            address._location_selected(str(self.root.parent))
            after.assert_called_once_with(1, self.dialog._navigate, str(self.root.parent))

    def test_selector_control_geometry_stays_aligned_after_resize(self):
        from DearUIQt.widgets import QRetainedItem
        from WinUx.dialogs.folder_browser_style import METRICS

        def rect(tag):
            geometry = QRetainedItem(tag).globalGeometry()
            return geometry.x(), geometry.y(), geometry.width(), geometry.height()

        for width in (560, 680, 900):
            dpg.configure_item(self.dialog.tag, width=width)
            self.dialog._apply_layout()
            for _ in range(4):
                self.frame()
            location = rect(self.dialog.address.tag)
            field = rect(self.dialog.folder_edit)
            accept = rect(self.dialog._accept_button)
            cancel = rect(self.dialog._reject_button)
            self.assertEqual(location[0], field[0], 'Location/filename must share a left edge')
            for control in (location, field, accept, cancel):
                self.assertEqual(control[3], METRICS.control_height)
            self.assertEqual(field[1], accept[1])
            self.assertEqual(accept[0], cancel[0])
            self.assertEqual(accept[2], cancel[2])
            self.assertGreaterEqual(cancel[1] - accept[1] - accept[3], METRICS.form_gap)
            for label_name, control in (('location', location), ('filename', field)):
                label = rect(self.dialog._form_labels[label_name].tag)
                self.assertAlmostEqual(label[1] + label[3] / 2, control[1] + control[3] / 2, delta=1)
            if hasattr(self.dialog, 'file_type'):
                combo = rect(self.dialog.file_type)
                self.assertEqual(combo[3], METRICS.control_height)
                self.assertEqual(combo[0], field[0])
                self.assertEqual(combo[2], field[2])
                self.assertEqual(combo[1], cancel[1])
                label = rect(self.dialog._form_labels['filter'].tag)
                self.assertAlmostEqual(label[1] + label[3] / 2, combo[1] + combo[3] / 2, delta=1)
        self.dialog._set_status('Example error', error=True)
        self.assertTrue(dpg.is_item_shown(self.dialog.status))
        self.dialog._set_status('Ready')
        self.assertFalse(dpg.is_item_shown(self.dialog.status))

    def test_selector_state_themes_restore_focus_disabled_and_provider_removal(self):
        dialog = self.dialog
        for kind, control in (
                ('editor', dialog._folder_edit_control),
                ('accept', dialog.control_wrapper(dialog._accept_button)),
                ('cancel', dialog.control_wrapper(dialog._reject_button))):
            with patch.object(control, '_focused', return_value=False):
                control._refresh_style()
                normal = control.theme()
            with patch.object(control, '_focused', return_value=True):
                control._refresh_style()
                focused = control.theme()
            self.assertNotEqual(focused, normal)
            control.setEnabled(False)
            self.assertEqual(control.theme(), dialog._selector_themes[(kind, False, True)])
            control.setEnabled(True)
            self.assertFalse(dpg.get_item_configuration(control.tag)['enabled'] is False)
            with patch.object(control, '_focused', return_value=False):
                before = len(dialog._selector_themes)
                for _ in range(10):
                    control._refresh_style()
                self.assertEqual(len(dialog._selector_themes), before)
        editor = dialog._folder_edit_control
        old_theme = editor._provider_previous_theme
        editor.setThemeProvider(None)
        self.assertEqual(editor.theme(), old_theme)
        with self.assertRaises(TypeError):
            editor.setThemeProvider('not callable')
        editor.setThemeProvider(dialog._selector_theme_provider('editor'))

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
            config = dpg.get_item_configuration(home)
            config["callback"](home, True, config["user_data"])
            self.assertFalse(navigate.called)
            self.dialog._commit_place_navigation()
            self.assertFalse(navigate.called, "navigation must wait for a release-render boundary")
            for _ in range(8):
                self.frame()
        navigate.assert_called_once_with(str(Path.home()))

    def test_sidebar_visual_layers_have_native_click_handlers(self):
        for button in self.dialog.place_buttons.values():
            overlay = next(visual['overlay'] for visual in self.dialog._places_tree._rendered.values()
                           if visual['selectable'] == button)
            registry = dpg.get_item_info(overlay)["handlers"]
            self.assertTrue(registry, "Sidebar icon/text layer must receive clicks")
            handlers = dpg.get_item_children(registry, 1)
            self.assertEqual(len(handlers), 1)
            config = dpg.get_item_configuration(handlers[0])
            with patch.object(self.dialog, "_navigate") as navigate:
                config["callback"](handlers[0], None, config["user_data"])
                self.assertFalse(navigate.called)
                self.dialog._commit_place_navigation()
                self.assertFalse(navigate.called)
                for _ in range(8):
                    self.frame()
                navigate.assert_called_once_with(dpg.get_item_configuration(button)["user_data"])

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
        # The location field stays a plain editable editor; breadcrumbs never
        # appear in this browser (see address bar `breadcrumbs=False`).
        self.assertTrue(dpg.is_item_shown(self.dialog.path_edit))
        self.assertFalse(dpg.is_item_shown(self.dialog.breadcrumbs))
        self.dialog.address.begin_edit()
        self.dialog._close_from_native()
        self.dialog._close_from_native()
        self.assertEqual(self.results, [None])

    # test_breadcrumb_click_navigates_parent superseded by
    # test_qt_location_field_remains_editable_and_offers_parent_locations:
    # the browser location field is now always editable (breadcrumbs=False) and
    # parent navigation is offered by the address-bar location dropdown.

    def test_list_mode_survives_filter_refresh(self):
        writes = []
        original = dpg.set_value
        def record(tag, value):
            if tag == self.dialog.filter_edit:
                import traceback
                writes.append((value, traceback.format_stack(limit=7)))
            return original(tag, value)
        writer = patch.object(dpg, "set_value", side_effect=record)
        writer.start()
        self.addCleanup(writer.stop)
        self.dialog._change_view("List")
        self.assertFalse(dpg.get_item_configuration(self.dialog.listbox.table)["header_row"])
        self.assertTrue(all(not dpg.get_item_configuration(tag)["show"]
                            for tag in self.dialog.listbox.detail_columns))
        dpg.set_value(self.dialog.filter_edit, "Al")
        self.dialog._filter_entries()
        for _ in range(3):
            self.frame()
            writes.append(("state", dpg.get_item_state(self.dialog.filter_edit), dpg.get_focused_item()))
        self.assertTrue(all(not dpg.get_item_configuration(tag)["show"]
                            for tag in self.dialog.listbox.detail_columns))
        self.assertEqual([item.text for item in self.dialog.listbox._values], ["Alpha"],
                         {"query": dpg.get_value(self.dialog.filter_edit),
                          "status": dpg.get_value(self.dialog.status),
                          "path": self.dialog._current_path, "writes": writes})
        self.assertFalse(dpg.get_item_configuration(self.dialog.listbox.table)["header_row"])
        self.dialog._change_view("Details")
        self.assertEqual(len(self.dialog.listbox.detail_columns), 2)

    def wait_create(self):
        deadline = time.monotonic() + 5
        while (self.dialog._creating_folder or dpg.get_value(self.dialog.status) == "Loading..."
               or self.dialog._rename_after_load is not None
               or (self.dialog._rename_path is not None
                   and not dpg.is_item_active(self.dialog._rename_editor))):
            self.frame()
            if time.monotonic() > deadline:
                self.fail("Folder creation did not finish")
            time.sleep(0.005)
        for _ in range(3):
            self.frame()

    def test_new_folder_is_created_and_selected_without_closing_dialog(self):
        button = self.dialog.new_folder_button
        dpg.get_item_configuration(button)["callback"](button, None, None)
        self.wait_create()
        created = self.root / "New folder"
        self.assertTrue(created.is_dir())
        self.assertEqual(self.dialog.listbox.currentData(), str(created))
        self.assertEqual(dpg.get_value(self.dialog.folder_edit), str(created))
        self.assertEqual(self.dialog._rename_path, str(created))
        self.assertEqual(dpg.get_value(self.dialog._rename_editor), "New folder")
        self.assertTrue(dpg.is_item_shown(self.dialog._rename_editor))
        self.assertTrue(dpg.is_item_active(self.dialog._rename_editor))
        self.assertTrue(dpg.is_item_focused(self.dialog._rename_editor))
        self.assertTrue(self.dialog.winfo_exists())
        self.assertFalse(self.results)
        self.dialog.invoke_default()
        self.assertFalse(self.results, "Enter must not accept the chooser while renaming")
        dpg.set_value(self.dialog._rename_editor, "Created folder")
        self.dialog._browser_key(None, dpg.mvKey_Return)
        self.wait_listing()
        self.assertTrue((self.root / "Created folder").is_dir())
        self.assertFalse(created.exists())
        self.assertEqual(self.dialog.listbox.currentData(), str(self.root / "Created folder"))
        self.assertIsNone(self.dialog._rename_path)
        self.assertFalse(self.results)

    def test_new_folder_rejects_path_and_existing_directory(self):
        self.dialog._show_new_folder()
        self.wait_create()
        dpg.set_value(self.dialog._rename_editor, "../outside")
        self.assertFalse(self.dialog._commit_folder_rename())
        self.assertIn("Could not rename folder", dpg.get_value(self.dialog.status))
        dpg.set_value(self.dialog._rename_editor, "Alpha")
        self.assertFalse(self.dialog._commit_folder_rename())
        self.assertIn("already exists", dpg.get_value(self.dialog.status))
        self.assertTrue((self.root / "Alpha" / "Nested").is_dir())
        self.dialog._close_from_escape()
        self.assertTrue(self.dialog.winfo_exists())
        self.assertIsNone(self.dialog._rename_path)
        self.assertTrue((self.root / "New folder").is_dir())

    def test_new_folder_uses_unique_default_name_and_escape_keeps_folder(self):
        (self.root / "New folder").mkdir()
        (self.root / "New folder (2)").mkdir()
        dpg.set_value(self.dialog.filter_edit, "Alpha")
        self.dialog._filter_entries()
        self.dialog._show_new_folder()
        self.wait_create()
        created = self.root / "New folder (3)"
        self.assertTrue(created.is_dir())
        self.assertEqual(self.dialog.listbox.currentData(), str(created))
        self.assertEqual(dpg.get_value(self.dialog.filter_edit), "")
        dpg.set_value(self.dialog._rename_editor, "Cancelled name")
        self.dialog._close_from_escape()
        self.assertTrue(created.is_dir())
        self.assertFalse((self.root / "Cancelled name").exists())
        self.assertIsNone(self.dialog._rename_path)
        self.assertTrue(self.dialog.winfo_exists())
        self.assertFalse(self.results)

    def test_new_folder_outside_click_commits_name(self):
        self.dialog._show_new_folder()
        self.wait_create()
        dpg.set_value(self.dialog._rename_editor, "Clicked away")
        with patch.object(dpg, "is_item_hovered", return_value=False):
            self.dialog._rename_outside_click()
        self.frame()
        self.wait_listing()
        self.assertTrue((self.root / "Clicked away").is_dir())
        self.assertIsNone(self.dialog._rename_path)

    def test_new_folder_create_error_reenables_button(self):
        with patch("WinUx.dialogs.local_folder_form.FileSystemModel.new_folder",
                   side_effect=OSError("Access denied")):
            self.dialog._show_new_folder()
            self.wait_create()
        self.assertIn("Access denied", dpg.get_value(self.dialog.status))
        self.assertTrue(dpg.get_item_configuration(self.dialog.new_folder_button)["enabled"])
        self.assertIsNone(self.dialog._rename_path)

    def test_new_folder_scrolls_to_editor_in_list_and_details_modes(self):
        for index in range(80):
            (self.root / "A{:03d}".format(index)).mkdir()
        self.dialog._refresh()
        self.wait_listing()
        for mode in ("List", "Details"):
            with self.subTest(mode=mode):
                self.dialog._change_view(mode)
                self.dialog._show_new_folder()
                self.wait_create()
                editor = self.dialog._rename_editor
                self.assertTrue(dpg.get_item_state(editor)["visible"])
                self.assertGreater(dpg.get_y_scroll(self.dialog.listbox.tag), 0)
                self.dialog._close_from_escape()
                self.assertIsNone(self.dialog._rename_editor)

    def test_new_folder_navigation_discards_pending_editor(self):
        self.dialog._show_new_folder()
        self.wait_create()
        self.dialog._navigate(str(self.root / "Alpha"))
        self.wait_listing()
        self.assertIsNone(self.dialog._rename_path)
        self.assertIsNone(self.dialog._rename_editor)
        self.assertEqual(self.dialog._current_path, str(self.root / "Alpha"))
        self.assertTrue((self.root / "New folder").is_dir())

    @unittest.skipUnless(os.name == "nt", "Windows character input")
    def test_new_folder_receives_typing_without_an_extra_click(self):
        import ctypes
        from ctypes import wintypes
        self.dialog._show_new_folder()
        self.wait_create()
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        hwnd = user32.FindWindowW(None, "WinUx folder browser check")
        self.assertTrue(hwnd)
        # Real WM_CHAR input goes through GLFW to whichever input owns focus.
        for character in "Focused folder":
            user32.SendMessageW(hwnd, 0x0102, ord(character), 1)
        for _ in range(3):
            self.frame()
        self.assertEqual(dpg.get_value(self.dialog._rename_editor), "Focused folder")
        self.dialog._browser_key(None, dpg.mvKey_Return)
        self.wait_listing()
        self.assertTrue((self.root / "Focused folder").is_dir())

    def open_context_menu(self, name="Alpha"):
        path = str(self.root / name)
        tag = self.dialog.listbox.items[path]
        x, y = dpg.get_item_rect_min(tag)
        with patch.object(dpg, "get_mouse_pos", return_value=(x + 30, y + 8)):
            self.dialog._folder_right_release()
        for _ in range(4):
            self.frame()
        self.assertTrue(self.dialog._folder_menu_is_open())
        self.assertTrue(self.dialog.winfo_exists())
        self.assertFalse(self.results)
        return path

    def trigger_context_action(self, action):
        menu = self.dialog._folder_context_menu
        left, top, right, bottom = dpg_window_rect(dpg, menu._rows[action], clip=True)
        with patch.object(dpg, "get_mouse_pos", return_value=((left + right) / 2,
                                                             (top + bottom) / 2)):
            menu._pointer_clicked()
        for _ in range(4):
            self.frame()

    def test_context_menu_selects_clicked_row_and_escape_only_dismisses_menu(self):
        self.dialog.listbox.setCurrentKey(str(self.root / "Beta"), select=True)
        target = self.open_context_menu()
        self.assertEqual(self.dialog.listbox.currentData(), target)
        self.assertIsNone(self.dialog.active_table)
        self.dialog._close_from_escape()
        self.assertFalse(self.dialog._folder_menu_is_open())
        self.assertIs(self.dialog.active_table, self.dialog.listbox)
        self.assertTrue(self.dialog.winfo_exists())
        self.assertFalse(self.results)

    def test_context_menu_rename_edits_existing_folder(self):
        self.open_context_menu("Beta")
        self.trigger_context_action("rename")
        self.wait_create()
        self.assertEqual(self.dialog._rename_path, str(self.root / "Beta"))
        self.assertTrue(dpg.is_item_active(self.dialog._rename_editor))
        dpg.set_value(self.dialog._rename_editor, "Renamed Beta")
        self.dialog._browser_key(None, dpg.mvKey_Return)
        self.wait_listing()
        self.assertTrue((self.root / "Renamed Beta").is_dir())
        self.assertFalse((self.root / "Beta").exists())

    def test_context_menu_open_navigates_clicked_folder(self):
        target = self.open_context_menu()
        self.trigger_context_action("open")
        self.wait_listing()
        self.assertEqual(self.dialog._current_path, target)
        self.assertFalse(self.results)

    def test_context_menu_select_returns_clicked_folder(self):
        target = self.open_context_menu("Beta")
        self.trigger_context_action("select")
        self.assertEqual(self.results, [target])

    def test_context_menu_copy_path_and_open_in_explorer(self):
        target = self.open_context_menu()
        with patch.object(dpg, "set_clipboard_text") as copy_path:
            self.trigger_context_action("copy_path")
        copy_path.assert_called_once_with(target)
        target = self.open_context_menu("Beta")
        with patch("WinUx.dialogs.local_folder_form.os.startfile") as open_folder:
            self.trigger_context_action("explorer")
        open_folder.assert_called_once_with(target)

    def test_context_menu_new_folder_and_refresh(self):
        self.open_context_menu()
        self.trigger_context_action("new_folder")
        self.wait_create()
        self.assertTrue(dpg.is_item_active(self.dialog._rename_editor))
        self.assertTrue((self.root / "New folder").is_dir())
        self.dialog._close_from_escape()
        self.open_context_menu()
        generation = self.dialog._generation
        self.trigger_context_action("refresh")
        self.wait_listing()
        self.assertGreater(self.dialog._generation, generation)

    def test_context_menu_background_disables_item_actions(self):
        self.dialog._show_folder_context_menu(None, (300, 200), self.dialog._current_path)
        for _ in range(4):
            self.frame()
        menu = self.dialog._folder_context_menu
        self.assertTrue(self.dialog._folder_menu_is_open())
        for action in ("open", "select", "rename", "copy_path", "explorer"):
            self.assertFalse(menu._find_spec(action)["enabled"])
        self.assertTrue(menu._find_spec("new_folder")["enabled"])
        self.assertTrue(menu._find_spec("refresh")["enabled"])

    def test_context_menu_ignores_stale_action_after_navigation(self):
        target = self.open_context_menu()
        context = self.dialog._folder_context_menu.context()
        self.dialog._navigate(str(self.root / "Beta"))
        self.wait_listing()
        self.dialog._run_folder_menu_action("select", context)
        self.assertFalse(self.results)
        self.assertNotEqual(self.dialog._current_path, target)

    def test_context_menu_outside_click_dismisses_without_closing_dialog(self):
        self.open_context_menu()
        with patch.object(dpg, "get_mouse_pos", return_value=(0, 0)):
            self.dialog._folder_menu_outside_click()
        for _ in range(3):
            self.frame()
        self.assertFalse(self.dialog._folder_menu_is_open())
        self.assertTrue(self.dialog.winfo_exists())
        self.assertFalse(self.results)

    def test_context_menu_registered_mouse_handler_activates_rename(self):
        from WinUx.runtime.dpg_callbacks import invoke_callback_job
        self.open_context_menu("Beta")
        menu = self.dialog._folder_context_menu
        left, top, right, bottom = dpg_window_rect(dpg, menu._rows["rename"], clip=True)
        handlers = dpg.get_item_children(menu._keyboard_registry, 1)
        handler = next(tag for tag in handlers if dpg.get_item_configuration(tag).get(
            "callback") == menu._pointer_clicked)
        callback = dpg.get_item_configuration(handler)["callback"]
        with patch.object(dpg, "get_mouse_pos", return_value=((left + right) / 2,
                                                             (top + bottom) / 2)):
            invoke_callback_job((callback, handler, dpg.mvMouseButton_Left, None))
        for _ in range(4):
            self.frame()
        self.wait_create()
        self.assertEqual(self.dialog._rename_path, str(self.root / "Beta"))
        self.assertTrue(dpg.is_item_active(self.dialog._rename_editor))

    def test_context_menu_enter_does_not_also_open_the_folder(self):
        self.open_context_menu("Beta")
        menu = self.dialog._folder_context_menu
        menu._set_active_action("rename")
        menu._key_pressed(user_data=dpg.mvKey_Return)
        # The browser also observes Return in the same DPG callback batch.
        self.dialog._browser_key(None, dpg.mvKey_Return)
        self.dialog.invoke_default()
        for _ in range(4):
            self.frame()
        self.wait_create()
        self.assertEqual(self.dialog._current_path, str(self.root))
        self.assertEqual(self.dialog._rename_path, str(self.root / "Beta"))
        self.assertFalse(self.results)

    def test_context_menu_rename_works_in_list_and_details_modes(self):
        for mode in ("List", "Details"):
            with self.subTest(mode=mode):
                self.dialog._change_view(mode)
                for _ in range(3):
                    self.frame()
                self.open_context_menu("Beta")
                self.trigger_context_action("rename")
                self.wait_create()
                self.assertTrue(dpg.is_item_active(self.dialog._rename_editor))
                self.dialog._close_from_escape()

    # test_sidebar_groups_can_collapse_and_expand superseded by
    # test_sidebar_rows_have_visible_full_width_hit_targets: sidebar sections
    # are now QTreeWidget top-level items (setRootSectionsVisible(False)); the
    # header/body drawlist pair no longer exists and collapse/expand is covered
    # by that suite plus setExpandOnItemClick.

    def test_browser_keyboard_shortcuts_dispatch_to_address_and_new_folder(self):
        with patch.object(dpg, "is_key_down", side_effect=lambda key: key == dpg.mvKey_LControl):
            self.dialog._browser_key(None, dpg.mvKey_L)
        self.assertTrue(self.dialog.address.editing)
        with patch.object(dpg, "is_key_down", side_effect=lambda key: key in
                          (dpg.mvKey_LControl, dpg.mvKey_LShift)):
            self.dialog._browser_key(None, dpg.mvKey_N)
        self.wait_create()
        self.assertIsNotNone(self.dialog._rename_path)
        self.assertFalse(self.dialog.address.editing)

    def test_new_folder_editor_fits_at_minimum_window_size(self):
        dpg.configure_item(self.dialog.tag, width=620, height=400)
        self.dialog._show_new_folder()
        self.wait_create()
        self.assertTrue(dpg.get_item_state(self.dialog._rename_editor)["visible"])
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
