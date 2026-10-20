"""Native open/save coverage for the shared WinUx browser selector."""
import sys
import time

import pytest


pytestmark = [pytest.mark.windows_native,
              pytest.mark.skipif(sys.platform != "win32", reason="Native DearPyGui browser")]


@pytest.fixture
def browser_ui():
    import dearpygui.dearpygui as dpg
    from WinUx.ui import StandaloneUiHost
    from WinUx.ui.components.toolbar import ResourceTextures
    from WinUx.platform.windows_icons import WindowsIconRegistry
    from WinUx.dialogs.floating_runtime import configure_context
    from DearUIQt.tooltip import reset_tooltip_runtime_resources

    dpg.create_context()
    reset_tooltip_runtime_resources()
    host = StandaloneUiHost(dpg)
    configure_context(host)
    dpg.create_viewport(title="File selector check", width=900, height=620)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    yield dpg, host
    host.pump()
    ResourceTextures.reset()
    WindowsIconRegistry.reset()
    reset_tooltip_runtime_resources()
    dpg.destroy_context()


def _wait(dpg, host, dialog):
    deadline = time.monotonic() + 5
    while dpg.get_value(dialog.status) == "Loading...":
        host.pump()
        dpg.render_dearpygui_frame()
        assert time.monotonic() < deadline, "Browser listing did not complete"
        time.sleep(.005)
    dpg.render_dearpygui_frame()


@pytest.mark.parametrize("directory", [True, False])
def test_physical_clicks_select_rows_and_do_not_navigate_on_single_click(browser_ui, tmp_path, directory):
    """Exercise GLFW/ImGui hit testing, not a direct setCurrentKey call."""
    import ctypes
    from ctypes import wintypes
    from WinUx.ui import FileSelector
    from WinUx.ui.native.native_dialog_host import find_process_window
    from WinUx.runtime.dpg_callbacks import run_callback_jobs

    dpg, host = browser_ui
    for name in ("Alpha", "Beta", "Gamma", "Delta"):
        (tmp_path / name).mkdir()
    (tmp_path / "Alpha" / "Inside").mkdir()
    (tmp_path / "sample.csv").write_text("1,2")
    selector = FileSelector(view=host, initial=str(tmp_path), directory=directory,
                            accepted=lambda path: None, extensions=(".csv",))
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.DWORD, ctypes.c_size_t]
    old = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(old))

    def pump(count=4):
        for _ in range(count):
            run_callback_jobs(dpg.get_callback_queue() or [])
            host.pump()
            dpg.render_dearpygui_frame()
            time.sleep(.01)

    def click(tag):
        x, y = dpg.get_item_rect_min(tag)
        width, height = dpg.get_item_rect_size(tag)
        point = wintypes.POINT(round(x + min(20, width / 2)), round(y + height / 2))
        assert user32.ClientToScreen(hwnd, ctypes.byref(point))
        user32.SetCursorPos(point.x, point.y)
        pump()
        user32.mouse_event(2, 0, 0, 0, 0)
        pump()
        user32.mouse_event(4, 0, 0, 0, 0)
        pump()

    try:
        selector.open()
        dialog = selector.dialog
        _wait(dpg, host, dialog)
        pump()
        hwnd = find_process_window("File selector check")
        user32.SetForegroundWindow(hwnd)
        if int(user32.GetForegroundWindow() or 0) != hwnd:
            pytest.skip("Windows did not grant foreground for physical selector input")
        for name, cell in (("Alpha", "name"), ("Beta", "icon"), ("Gamma", "date"), ("Delta", "type")):
            key = str(tmp_path / name)
            row = dialog.listbox.items[key]
            if cell == "icon":
                tag = dpg.get_item_parent(dialog.listbox.icons[key])
            elif cell in ("date", "type"):
                tag = dialog.listbox.detail_texts[key][0 if cell == "date" else 1]
            else:
                tag = row
            click(tag)
            assert dialog._current_path == str(tmp_path), "one click must not enter a folder"
            assert dialog.listbox.current == key, (cell, dialog.listbox.current)
            assert key in dialog.listbox.selected
        # A real double-click rebuilds the row widgets; the next click must
        # still reach the child folder, rather than leaving ImGui input stuck.
        row = dialog.listbox.items[str(tmp_path / "Alpha")]
        click(row)
        click(row)
        _wait(dpg, host, dialog)
        pump()
        assert dialog._current_path == str(tmp_path / "Alpha")
        key = str(tmp_path / "Alpha" / "Inside")
        click(dialog.listbox.items[key])
        assert dialog.listbox.current == key
        assert key in dialog.listbox.selected
        selector.close()
        pump()
        selector = FileSelector(view=host, initial=str(tmp_path), directory=not directory,
                                accepted=lambda path: None, extensions=(".csv",))
        selector.open()
        dialog = selector.dialog
        _wait(dpg, host, dialog)
        pump()
        key = str(tmp_path / "Beta")
        click(dialog.listbox.items[key])
        assert dialog.listbox.current == key
        assert key in dialog.listbox.selected
    finally:
        user32.mouse_event(4, 0, 0, 0, 0)
        user32.SetCursorPos(old.x, old.y)
        selector.close()


def test_open_selector_reuses_folder_browser_and_filters_files(browser_ui, tmp_path):
    from WinUx.ui import FileSelector
    from WinUx.dialogs.local_folder_form import LocalFolderDialog, FolderListView

    dpg, host = browser_ui
    (tmp_path / "nested").mkdir()
    (tmp_path / "chart.PNG").write_bytes(b"image")
    (tmp_path / "notes.txt").write_text("notes")
    results = []
    selector = FileSelector(view=host, initial=str(tmp_path), accepted=results.append,
                            extensions=(".png",))
    try:
        selector.open()
        dialog = selector.dialog
        _wait(dpg, host, dialog)
        assert isinstance(dialog, LocalFolderDialog)
        assert isinstance(dialog.listbox, FolderListView)
        assert dpg.get_item_info(dialog.tag)["type"] == "mvAppItemType::mvWindowAppItem"
        assert {item.text for item in dialog.listbox._values} == {"nested", "chart.PNG"}
        assert dialog._entry_types[str(tmp_path / "chart.PNG")] == "PNG File"
        assert all(dpg.does_item_exist(tag) for tag in (
            dialog.places, dialog.path_edit, dialog.breadcrumbs, dialog.back_button,
            dialog.forward_button, dialog.up_button, dialog.file_type))
        dialog.listbox.setCurrentKey(str(tmp_path / "chart.PNG"), select=True)
        assert dpg.get_value(dialog.file_edit) == "chart.PNG"
        dialog._select_folder()
        assert results == [str(tmp_path / "chart.PNG")]
        dialog.finish(None)
        assert len(results) == 1
    finally:
        selector.close()


def test_rebuilt_rows_reject_old_visual_and_selectable_callbacks(browser_ui, tmp_path):
    from WinUx.ui import FileSelector

    dpg, host = browser_ui
    child = tmp_path / "nested"
    child.mkdir()
    selector = FileSelector(view=host, initial=str(tmp_path), accepted=lambda path: None)
    try:
        selector.open()
        dialog = selector.dialog
        _wait(dpg, host, dialog)
        key = str(child)
        old_row = dialog.listbox.items[key]
        old_registry = dialog.listbox._visual_hit_registries[0]
        handler = dpg.get_item_children(old_registry, 1)[0]
        old_callback = dpg.get_item_configuration(handler)["callback"]
        dialog._filter_entries()
        assert dialog.listbox.items[key] != old_row
        assert not dpg.does_item_exist(old_registry)
        old_callback(handler, [0, old_row], key)
        dialog.listbox._clicked(old_row, True, key)
        assert dialog.listbox.current is None
        assert not dialog.listbox.selected
        assert dialog._pending_row_activation is None
    finally:
        selector.close()


def test_navigation_all_files_search_and_double_click(browser_ui, tmp_path):
    from WinUx.ui import FileSelector

    dpg, host = browser_ui
    child = tmp_path / "nested"
    child.mkdir()
    (child / "sample.csv").write_text("1,2")
    (tmp_path / "other.txt").write_text("other")
    results = []
    selector = FileSelector(view=host, initial=str(tmp_path), accepted=results.append,
                            extensions=(".csv",))
    try:
        selector.open()
        dialog = selector.dialog
        _wait(dpg, host, dialog)
        dialog._enter_key(str(child))
        _wait(dpg, host, dialog)
        assert dialog._current_path == str(child)
        dialog._go_back()
        _wait(dpg, host, dialog)
        dialog._file_type_changed(None, "All files (*.*)")
        _wait(dpg, host, dialog)
        dpg.set_value(dialog.filter_edit, "OTHER")
        dialog._filter_entries()
        assert [item.text for item in dialog.listbox._values] == ["other.txt"]
        dialog._enter_key(str(tmp_path / "other.txt"))
        assert results == [str(tmp_path / "other.txt")]
    finally:
        selector.close()


def test_save_default_name_extension_and_overwrite(browser_ui, tmp_path):
    from WinUx.ui import FileSelector

    dpg, host = browser_ui
    (tmp_path / "existing.csv").write_text("original")
    results = []
    selector = FileSelector(view=host, initial=str(tmp_path), accepted=results.append,
                            extensions=(".csv",), save=True, default_filename="result")
    try:
        selector.open()
        dialog = selector.dialog
        _wait(dpg, host, dialog)
        assert dpg.get_value(dialog.file_edit) == "result"
        dialog._select_folder()
        assert results == [str(tmp_path / "result.csv")]
        assert not (tmp_path / "result.csv").exists()
        selector.open()
        dialog = selector.dialog
        _wait(dpg, host, dialog)
        dpg.set_value(dialog.file_edit, "existing.csv")
        dialog._select_folder()
        assert len(results) == 1
        assert "Press Save again" in dpg.get_value(dialog.status)
        assert dialog._overwrite_path == str(tmp_path / "existing.csv")
        dialog._select_folder()
        assert results[-1] == str(tmp_path / "existing.csv"), (dpg.get_value(dialog.status),
                                                              dialog._finished, dialog._overwrite_path)
        assert (tmp_path / "existing.csv").read_text() == "original"
    finally:
        selector.close()


@pytest.mark.parametrize("filename,message", [
    ("missing.png", "does not exist"), ("wrong.txt", "supported file type"),
])
def test_invalid_open_keeps_selector_active(browser_ui, tmp_path, filename, message):
    from WinUx.ui import FileSelector

    dpg, host = browser_ui
    results = []
    selector = FileSelector(view=host, initial=str(tmp_path), accepted=results.append,
                            extensions=(".png",))
    try:
        selector.open()
        dialog = selector.dialog
        _wait(dpg, host, dialog)
        dpg.set_value(dialog.file_edit, filename)
        dialog._select_folder()
        assert not results
        assert message in dpg.get_value(dialog.status)
        assert dialog.winfo_exists()
    finally:
        selector.close()


def test_plotdigitizer_uses_shared_selector_and_closes_child(browser_ui, tmp_path):
    from WinUx.plotdigitizer.ui import PlotDigitizerDialog
    from WinUx.ui import FileSelector
    from WinUx.dialogs.local_file_form import LocalFileDialog

    dpg, host = browser_ui
    dialog = PlotDigitizerDialog(host)
    try:
        dialog._file_directory = str(tmp_path)
        dialog._choose_open_image()
        assert isinstance(dialog._file_dialog, FileSelector)
        selector = dialog._file_dialog.dialog
        assert isinstance(selector, LocalFileDialog)
        _wait(dpg, host, selector)
        assert ".png" in selector.extensions
        assert selector._current_path == str(tmp_path)
        selector._close_from_native()
        assert dpg.get_value(dialog.status) == ""
        assert not dpg.get_item_configuration(dialog.status)["show"]
        dialog._choose_export_csv()
        selector = dialog._file_dialog.dialog
        _wait(dpg, host, selector)
        assert selector.save
        assert dpg.get_value(selector.file_edit) == "digitized_data.csv"
        dialog.destroy()
        assert not selector.winfo_exists()
    finally:
        dialog.destroy()
