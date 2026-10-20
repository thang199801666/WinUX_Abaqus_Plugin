"""Real-renderer check: root QMenu popup/hide/popup cycle stays reliable."""
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


SPEC = [("Item A", "a", None), ("---", None),
        {"id": "grp", "label": "More", "children": [("Child", "b", None)]}]


def frame(view):
    view.drain()
    dpg.render_dearpygui_frame()
    dpg.run_callbacks(dpg.get_callback_queue())
    time.sleep(0.004)


def shown(tag):
    try:
        return bool(dpg.is_item_shown(tag))
    except Exception:
        return None


failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + " " + str(detail))
    if not ok:
        failures.append(name)


def main():
    view = NoView()
    dpg.create_context()
    configure_context(view)
    dpg.create_viewport(title="menu cycle check", width=600, height=400)
    dpg.setup_dearpygui()
    dpg.show_viewport()

    menu = QMenu(SPEC, min_width=180, max_width=360)
    tag = menu.tag
    try:
        for cycle in range(4):
            menu.setActions(SPEC)          # real callers rebuild before popup
            ok = menu.popup((30 + 10 * cycle, 30))
            frame(view)
            check("cycle %d popup opens" % cycle, ok and shown(tag))
            menu._row_hovered(user_data="grp")
            for _ in range(4):
                frame(view)
            sub = menu._submenus.get("grp")
            check("cycle %d submenu opens" % cycle,
                  sub is not None and shown(sub.tag))
            menu.hide()
            for _ in range(3):
                frame(view)
            check("cycle %d hides" % cycle, shown(tag) is False)
    finally:
        try:
            menu.hide()
        except Exception:
            pass
        dpg.destroy_context()
    print("RESULT", "OK" if not failures else "FAILED")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
