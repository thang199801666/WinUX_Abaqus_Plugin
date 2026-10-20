"""Run: abaqus python examples/qt_combobox_demo.py [--smoke]."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import WinUx  # Select the installed native renderer before importing DPG.
    from DearUIQt.backends import get_backend
    from DearUIQt.backends.native_windows import NativeWindowBackend
    from DearUIQt.core.application import QApplication
    from DearUIQt.gui import QFontDatabase
    from DearUIQt.runtime import QGuiRuntime, StandaloneUiHost
    from DearUIQt.themes import fusion_desktop_theme
    from DearUIQt.widgets import QComboBox

    backend = get_backend()
    backend.create_context()
    backend.configure_app(manual_callback_management=True)
    combos, app, fonts = [], None, None
    try:
        NativeWindowBackend(backend).enable()
        host = StandaloneUiHost(backend)
        app = QApplication(after=host.after)
        app.installInputBackend(backend)
        runtime = QGuiRuntime(backend)
        runtime.setApplicationTheme(fusion_desktop_theme())
        fonts = QFontDatabase()
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        if font_path.is_file():
            font = fonts.addApplicationFont(str(font_path), 15)
            if font is not None:
                runtime.setApplicationFont(font)
        backend.create_viewport(title="Qt-style ComboBox", width=420, height=390)
        with backend.window(tag="qt_combo_demo"):
            backend.add_text("Choice")
            combo = QComboBox(
                ["Entity (E)", "Integer (I)", "Player (P)", "String (S)", "Unit (U)"],
                parent="qt_combo_demo", after=host.after, width=270)
            combos.append(combo)
            backend.add_spacer(height=12)
            backend.add_text("Scrollable list")
            long_combo = QComboBox(["Option {}".format(i + 1) for i in range(30)],
                                  parent="qt_combo_demo", after=host.after, width=270)
            long_combo.setMaxVisibleItems(6)
            combos.append(long_combo)
            backend.add_spacer(height=12)
            backend.add_text("Disabled")
            disabled = QComboBox(["Unavailable"], parent="qt_combo_demo", after=host.after, width=270)
            disabled.setEnabled(False)
            combos.append(disabled)
            backend.add_spacer(height=12)
            status = backend.add_text("Selected: Entity (E)")
            combo.currentTextChanged.connect(lambda text: backend.set_value(status, "Selected: " + text))
            backend.add_text("F4 / Alt+Down: open  |  Enter: select  |  Esc: cancel")
        backend.setup_dearpygui()
        backend.set_primary_window("qt_combo_demo", True)
        backend.show_viewport()
        frames = 0
        while backend.is_dearpygui_running():
            host.pump()
            backend.render_dearpygui_frame()
            backend.run_callbacks(backend.get_callback_queue())
            frames += 1
            if "--smoke" in sys.argv:
                if frames == 5:
                    combo.showPopup()
                elif frames == 15:
                    combo.hidePopup()
                elif frames >= 25:
                    break
    finally:
        for combo in combos:
            combo.delete()
        if app is not None:
            app.delete()
        if fonts is not None:
            fonts.delete()
        backend.destroy_context()


if __name__ == "__main__":
    main()
