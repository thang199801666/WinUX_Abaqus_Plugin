"""Shared Fusion controls: abaqus python examples/qt_controls_demo.py [--smoke]."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import WinUx  # Select the installed renderer before constructing controls.
    from DearUIQt.backends import get_backend
    from DearUIQt.backends.native_windows import NativeWindowBackend
    from DearUIQt.core.application import QApplication
    from DearUIQt.gui import QFontDatabase
    from DearUIQt.runtime import QGuiRuntime, StandaloneUiHost
    from DearUIQt.themes import fusion_desktop_theme
    from DearUIQt.widgets import QPushButton, QLineEdit, QCheckBox, QSpinBox, QTabWidget

    b = get_backend()
    b.create_context()
    b.configure_app(manual_callback_management=True)
    widgets, app, fonts = [], None, None
    try:
        NativeWindowBackend(b).enable()
        host = StandaloneUiHost(b)
        app = QApplication(after=host.after)
        app.installInputBackend(b)
        runtime = QGuiRuntime(b)
        runtime.setApplicationTheme(fusion_desktop_theme(background=(240, 240, 240, 255)))
        fonts = QFontDatabase()
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        if font_path.is_file():
            font = fonts.addApplicationFont(str(font_path), 15)
            if font is not None:
                runtime.setApplicationFont(font)
        b.create_viewport(title="Qt Fusion controls", width=560, height=390)
        with b.window(tag="qt_controls_demo"):
            with b.group(horizontal=True):
                normal = QPushButton("Button", width=100)
                default = QPushButton("Default", width=100, default=True)
                disabled = QPushButton("Disabled", width=100)
                disabled.setEnabled(False)
                widgets.extend((normal, default, disabled))
            b.add_spacer(height=8)
            b.add_text("Line edit")
            edit = QLineEdit("Editable text", width=320)
            widgets.append(edit)
            b.add_text("Spin box")
            spin = QSpinBox(4, width=160)
            widgets.append(spin)
            check = QCheckBox("Fusion checkbox", checked=True)
            widgets.append(check)
            tabs = QTabWidget()
            widgets.append(tabs)
            first, second = tabs.addTab("General"), tabs.addTab("Advanced")
            b.add_text("Selected tabs use a light face and a crisp edge.", parent=first.tag)
            b.add_text("Native mouse and keyboard navigation are unchanged.", parent=second.tag)
        b.setup_dearpygui()
        b.set_primary_window("qt_controls_demo", True)
        b.show_viewport()
        count = 0
        while b.is_dearpygui_running():
            host.pump()
            b.render_dearpygui_frame()
            b.run_callbacks(b.get_callback_queue())
            count += 1
            if "--smoke" in sys.argv:
                if count == 5:
                    edit.setText("Updated text")
                    check.setChecked(False)
                    spin.stepBy(1)
                    tabs.setCurrentIndex(1)
                elif count >= 20:
                    assert edit.text() == "Updated text"
                    assert not check.isChecked() and spin.value() == 5
                    assert tabs.currentIndex() == 1
                    assert not disabled.isEnabled()
                    print("QT_CONTROLS_NATIVE_OK")
                    break
    finally:
        for widget in reversed(widgets):
            widget.delete()
        if app is not None:
            app.delete()
        if fonts is not None:
            fonts.delete()
        b.destroy_context()


if __name__ == "__main__":
    main()
