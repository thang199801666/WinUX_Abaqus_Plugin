"""Micro-test: find a reliable recipe for re-showing a QMenu root popup
after the DPG engine auto-dismisses it (config.show flipped to False)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import WinUx  # noqa: E402,F401
import dearpygui.dearpygui as dpg  # noqa: E402
from DearUIQt.widgets import QMenu  # noqa: E402
from WinUx.dialogs.floating_runtime import configure_context  # noqa: E402


class NoView:
    def after(self, delay, callback, *args):
        callback(*args)

    def drain(self):
        pass


SPEC = [
    ("Check INP", "check_inp", None),
    {"id": "group1", "label": "Quick Upload", "children": [
        ("Upload *.inp", "quick:.inp", None)]},
    ("Open", "command:open", None),
]


def frame(view):
    view.drain()
    dpg.render_dearpygui_frame()
    dpg.run_callbacks(dpg.get_callback_queue())
    time.sleep(0.004)


def shown(item):
    try:
        return bool(dpg.is_item_shown(item))
    except Exception:
        return None


def main():
    view = NoView()
    dpg.create_context()
    configure_context(view)
    dpg.create_viewport(title="reshow check", width=600, height=400)
    dpg.setup_dearpygui()
    dpg.show_viewport()

    menu = QMenu(SPEC, min_width=200, max_width=400)
    tag = menu.tag
    try:
        menu.popup((30, 30))
        for _ in range(5):
            frame(view)
        print("show #1:", shown(tag))

        # Open the submenu then wait — earlier observed engine dismissal here.
        menu._row_hovered(user_data="group1")
        for _ in range(8):
            frame(view)
        print("after submenu:", "root", shown(tag))
        for _ in range(10):
            frame(view)
            if shown(tag) is False:
                print("root dismissed at frame", _)
                break
        print("final:", "root", shown(tag))

        # Recipe A: show=False, frame, show=True
        dpg.configure_item(tag, show=False)
        frame(view)
        dpg.configure_item(tag, show=True)
        frame(view)
        print("recipe A:", shown(tag))
        frame(view)
        print("recipe A+1:", shown(tag))

        # Recipe B: menu.popup() again (uses set_item_pos + show=True)
        menu.popup((30, 30))
        frame(view)
        print("recipe B (popup()):", shown(tag))
        frame(view)
        print("recipe B+1:", shown(tag))

        # Recipe C: configure popup=True + show=True (resets shownLastFrame path)
        dpg.configure_item(tag, popup=True, show=True)
        frame(view)
        print("recipe C:", shown(tag))
        frame(view)
        print("recipe C+1:", shown(tag))
    finally:
        try:
            menu.hide()
        except Exception:
            pass
        dpg.destroy_context()


if __name__ == "__main__":
    main()
