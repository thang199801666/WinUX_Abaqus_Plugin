"""Run from the repository root: abaqus python examples/dearuiqt_demo.py."""
import sys
from pathlib import Path

# Running a script by filename does not put the repository root on sys.path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))


def main():
    import dearpygui.dearpygui as dpg
    from DearUIQt import (
        StandaloneUiHost, ToolWindow, QLabel, QAction, QPushButton, QMenu,
    )

    dpg.create_context()
    try:
        host = StandaloneUiHost(dpg)
        window = ToolWindow(host, "DearUIQt demo", 540, 300)
        label = window.own_widget(QLabel("Ready", parent=window.content, after=host.after))
        update = window.own_widget(QAction("Update", after=host.after))
        update.triggered.connect(lambda checked: label.setText("One action shared by button and menu"))
        button = window.own_widget(QPushButton(parent=window.content, after=host.after))
        button.setDefaultAction(update)
        menu = window.own_widget(QMenu([update], after=host.after))
        window.action("Commands", menu.popup)
        window.action("Close", window.reject)
        window.create_timer(1000, lambda: label.setText("Owned timer fired"), single_shot=True)
        dpg.create_viewport(title="DearUIQt demo", width=540, height=300)
        dpg.set_primary_window(window.tag, True)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        while dpg.is_dearpygui_running() and window.winfo_exists():
            for job in dpg.get_callback_queue() or []:
                dpg.run_callbacks([job])
            host.pump()
            dpg.render_dearpygui_frame()
        window.destroy()
        host.pump()
    finally:
        dpg.destroy_context()


if __name__ == "__main__":
    main()
