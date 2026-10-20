"""Exercise the shared Qt-style combo with the real native renderer."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import WinUx
from DearUIQt.backends import dpg
from DearUIQt.backends.native_windows import NativeWindowBackend
from DearUIQt.backends.dearpygui import dpg_window_rect
from DearUIQt.core import QEvent, QKeyEvent, Qt
from DearUIQt.core.application import QApplication
from DearUIQt.widgets import QComboBox
from DearUIQt.runtime import StandaloneUiHost
from DearUIQt.runtime import QGuiRuntime
from DearUIQt.themes import fusion_desktop_theme
from DearUIQt.input_gate import popup_input_active


def main():
    dpg.create_context()
    dpg.configure_app(manual_callback_management=True)
    app = None
    combos = []
    try:
        NativeWindowBackend(dpg).enable()
        host = StandaloneUiHost(dpg)
        app = QApplication(after=host.after)
        app.installInputBackend(dpg)
        QGuiRuntime().setApplicationTheme(fusion_desktop_theme())
        dpg.create_viewport(title="Qt combo check", width=500, height=400, x_pos=100, y_pos=100)
        values = ["Entity (E)", "Integer (I)", "Player (P)", "String (S)", "Unit (U)"]
        with dpg.window(tag="combo_check_root", width=460, height=350, no_title_bar=True):
            combo = QComboBox(values, parent="combo_check_root", width=250, after=host.after)
            combos.append(combo)
            long_combo = QComboBox(["Item {}".format(i) for i in range(30)],
                                   parent="combo_check_root", width=250, after=host.after)
            combos.append(long_combo)
            editable_combo = QComboBox(["saved-host"], current="editable-value", editable=True,
                                       parent="combo_check_root", width=250, after=host.after)
            combos.append(editable_combo)
        dpg.setup_dearpygui()
        dpg.set_primary_window("combo_check_root", True)
        dpg.show_viewport()

        def frames(count=10):
            for _ in range(count):
                host.pump()
                dpg.render_dearpygui_frame()
                dpg.run_callbacks(dpg.get_callback_queue())

        def key(key):
            assert app.dispatchKeyEvent(QKeyEvent(QEvent.KeyPress, key))
            frames(3)

        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

        def click(x, y):
            hwnd = user32.FindWindowW(None, "Qt combo check")
            assert hwnd
            origin = wintypes.POINT()
            user32.ClientToScreen(hwnd, ctypes.byref(origin))
            x, y = round(x - origin.x), round(y - origin.y)
            lparam = (y << 16) | (x & 0xFFFF)
            user32.PostMessageW(hwnd, 0x0200, 0, lparam)
            frames(3)
            user32.PostMessageW(hwnd, 0x0201, 1, lparam)
            frames(2)
            user32.PostMessageW(hwnd, 0x0202, 0, lparam)
            frames()

        frames()
        changed, activated = [], []
        combo.currentIndexChanged.connect(changed.append)
        combo.activated.connect(activated.append)
        assert combo.showPopup()
        frames()
        popup = combo._choice_popup
        assert popup.isVisible() and popup._active_action == "0"
        assert popup_input_active()
        if "--snapshot" in sys.argv:
            import os
            snapshot = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "opencode" / "qt-combobox.png"
            dpg.output_frame_buffer(str(snapshot))
            frames(3)
        field_rect = dpg_window_rect(dpg, combo.tag)
        popup_rect = dpg_window_rect(dpg, popup.tag)
        assert abs(field_rect[0] - popup_rect[0]) <= 1, (field_rect, popup_rect)
        key(Qt.Key_Down)
        assert popup._active_action == "1" and combo.currentIndex() == 0
        key(Qt.Key_Escape)
        assert not popup.isVisible() and not changed and not activated
        assert not popup_input_active()

        assert combo.showPopup()
        frames()
        key(Qt.Key_End)
        key(Qt.Key_Return)
        assert combo.currentText() == "Unit (U)", combo.currentText()
        assert changed == [4] and activated == [4], (changed, activated)
        assert not popup_input_active() and app.mouseGrabberObject() is None
        arrow_triangle = dpg.get_item_configuration(combo._choice_field._chevron)
        assert arrow_triangle["p1"][0] > combo._choice_field._width - 30
        assert arrow_triangle["p3"][1] > arrow_triangle["p1"][1]

        # The complete preview opens the list, not only the arrow strip.
        field_rect = dpg_window_rect(dpg, combo.tag)
        click(field_rect[0] + 20, (field_rect[1] + field_rect[3]) / 2)
        assert combo.popupVisible(), ("Clicking the preview did not open the popup", field_rect,
            dpg.get_mouse_pos(local=False), dpg_window_rect(dpg, combo._choice_field.button),
            dpg.get_item_state(combo._choice_field.button),
            dpg.get_item_configuration(combo._choice_field.button))
        row_rect = dpg_window_rect(dpg, popup._rows["1"])
        click(row_rect[0] + 12, (row_rect[1] + row_rect[3]) / 2)
        assert combo.currentIndex() == 1 and not combo.popupVisible()
        assert activated == [4, 1], activated

        # Opening from the arrow and dismissing outside must release input.
        field_rect = dpg_window_rect(dpg, combo.tag)
        click(field_rect[2] - 8, (field_rect[1] + field_rect[3]) / 2)
        assert combo.popupVisible(), "Arrow did not open the popup"
        root_rect = dpg_window_rect(dpg, "combo_check_root")
        click(root_rect[2] - 20, root_rect[3] - 20)
        assert not combo.popupVisible() and not popup_input_active()

        # Exercise actual native key delivery as well as direct Qt events.
        combo.setFocus()
        frames(3)
        hwnd = user32.FindWindowW(None, "Qt combo check")
        user32.PostMessageW(hwnd, 0x0100, 0x73, 0)  # F4
        user32.PostMessageW(hwnd, 0x0101, 0x73, 0)
        frames()
        assert combo.popupVisible(), "Native F4 did not open the list"
        user32.PostMessageW(hwnd, 0x0100, 0x1B, 0)  # Escape
        user32.PostMessageW(hwnd, 0x0101, 0x1B, 0)
        frames()
        assert not combo.popupVisible() and not popup_input_active()

        long_combo.setMaxVisibleItems(5)
        long_combo.setCurrentIndex(20)
        assert long_combo.showPopup()
        frames()
        config = dpg.get_item_configuration(long_combo._choice_popup.tag)
        assert config["height"] == 5 * long_combo._choice_popup.ROW_HEIGHT + 2
        assert not config["no_scrollbar"]
        assert dpg.get_y_scroll(long_combo._choice_popup.tag) > 0
        key(Qt.Key_Escape)
        combo.setEnabled(False)
        assert not combo.showPopup()
        rect = dpg_window_rect(dpg, combo.tag)
        click(rect[2] - 8, (rect[1] + rect[3]) / 2)
        assert not combo.popupVisible(), "Disabled combo accepted an arrow click"
        combo.setEnabled(True)
        assert combo.showPopup()
        combo.hide()
        assert not combo.popupVisible() and not popup_input_active()

        frames()
        # Click-to-edit must work without calling setFocus() programmatically.
        field = editable_combo._choice_field
        def editor_bounds():
            x, y = dpg.get_item_rect_min(field.button)
            width, height = dpg.get_item_rect_size(field.button)
            return x, y, x + width, y + height
        editor = editor_bounds()
        arrow = dpg_window_rect(dpg, field._arrow_host)
        assert editor[2] <= arrow[0] + 1, (editor, arrow)
        click(editor[0] + 25, (editor[1] + editor[3]) / 2)
        assert dpg.get_item_state(field.button)["active"], "Preview click did not activate the editor"
        assert not editable_combo.popupVisible(), "Typing area opened history instead of editing"
        before = editable_combo.currentText()
        user32.PostMessageW(hwnd, 0x0102, ord("Z"), 0)
        frames()
        typed = editable_combo.currentText()
        assert typed != before and "Z" in typed, typed
        user32.PostMessageW(hwnd, 0x0100, 0x08, 0)  # Backspace
        frames(2)
        user32.PostMessageW(hwnd, 0x0101, 0x08, 0)
        frames()
        assert editable_combo.currentText() == before
        editable_combo.setFixedWidth(320)
        frames()
        assert editable_combo.currentText() == before, "Resize overwrote the edited text"
        editor = editor_bounds()
        arrow = dpg_window_rect(dpg, field._arrow_host)
        assert editor[2] <= arrow[0] + 1, (editor, arrow)
        click((arrow[0] + arrow[2]) / 2, (arrow[1] + arrow[3]) / 2)
        assert editable_combo.popupVisible(), "Separate history arrow did not open"
        editable_combo.hidePopup()
        assert not popup_input_active()
        print("QT_COMBOBOX_NATIVE_OK", json.dumps({"changed": changed, "activated": activated}))
    finally:
        for combo in combos:
            combo.delete()
        if app is not None:
            app.delete()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
