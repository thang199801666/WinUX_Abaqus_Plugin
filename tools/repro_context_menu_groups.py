"""Reproduce file-list context menu group (submenu) behavior headlessly.

Mirrors ExplorerListView usage: QMenu built once with min/max widths, then
each popup calls setActions() with the same normalized spec before popup().
Exercises hover-open, click-open, submenu switching, leaf clicks and the
keyboard path for group rows.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import WinUx  # noqa: E402,F401  (registers context configuration)
import dearpygui.dearpygui as dpg  # noqa: E402
from DearUIQt.widgets import QMenu  # noqa: E402
from WinUx.dialogs.floating_runtime import configure_context  # noqa: E402


class NoView:
    def after(self, delay, callback, *args):
        callback(*args)

    def drain(self):
        pass


def frame(view):
    view.drain()
    dpg.render_dearpygui_frame()
    dpg.run_callbacks(dpg.get_callback_queue())
    time.sleep(0.005)


ITEM_MENU = [
    {"id": "check_odb_local", "label": "Check ODB", "action": "check_odb",
     "icon": None, "enabled": False},
    ("Check INP", "check_inp", None),
    ("---", None),
    {"id": "quick_upload_group", "label": "Quick Upload", "icon": None,
     "children": [
         ("Upload *.inp", "quick:.inp", None),
         ("Upload *.dat", "quick:.dat", None),
     ]},
    {"id": "new_group", "label": "New", "icon": None, "children": [
        {"label": "New Folder", "action": "command:new_folder", "shortcut": "F7"},
        {"label": "New File", "action": "command:new_file"},
    ]},
    ("---", None),
    ("Open", "command:open", None),
    ("Copy", "command:copy", None),
    ("Paste", "command:paste", None),
]

failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    if not condition:
        failures.append(name)
    print("%s %s %s" % (status, name, detail))


def main():
    view = NoView()
    dpg.create_context()
    configure_context(view)
    dpg.create_viewport(title="context menu group check", width=720, height=480)
    dpg.setup_dearpygui()
    dpg.show_viewport()

    # Report the raw trigger for a submenu that never became visible.
    def diagnose_submenu_open(submenu):
        b = submenu.backend
        try:
            b.configure_item(submenu.tag, show=True)
            try:
                b.focus_item(submenu.tag)
            except Exception:
                pass
            print("raw show OK, shown:", dpg.is_item_shown(submenu.tag))
        except BaseException:
            traceback.print_exc()

    menu = None
    triggered = []

    try:
        menu = QMenu(ITEM_MENU, min_width=266, max_width=420)
        menu.triggered.connect(lambda action, context=None: triggered.append(action))

        # Popup #1: hover-open the group, then click a leaf.
        menu.setActions(ITEM_MENU)
        menu.popup((40, 40))
        for _ in range(5):
            frame(view)
        menu._row_hovered(user_data="quick_upload_group")
        for _ in range(5):
            frame(view)
        sub1 = menu._submenus.get("quick_upload_group")
        check("hover opens submenu", sub1 is not None and dpg.is_item_shown(sub1.tag))
        check("hover highlights row", menu._active_action == "quick_upload_group",
              menu._active_action)
        triggered.clear()
        sub1._row_clicked(user_data="quick:.inp")
        for _ in range(4):
            frame(view)
        check("leaf click triggers", triggered == ["quick:.inp"], triggered)
        check("leaf click closes menu", not dpg.is_item_shown(menu.tag))

        # Popup #2: rows are rebuilt via setActions; group must still respond.
        menu.setActions(ITEM_MENU)
        menu.popup((40, 40))
        for _ in range(6):
            frame(view)
        spec2 = menu._row_specs.get("new_group") or {"children": []}
        menu._row_clicked(user_data="new_group")
        for _ in range(5):
            frame(view)
        sub2 = menu._submenus.get("new_group")
        check("click on group opens submenu (2nd popup)",
              sub2 is not None and dpg.is_item_shown(sub2.tag))

        # Switch to the sibling group while a submenu is open.
        menu._row_hovered(user_data="quick_upload_group")
        for _ in range(5):
            frame(view)
        sub1 = menu._submenus.get("quick_upload_group")
        check("sibling hover switches submenu",
              sub2 is not None and not dpg.is_item_shown(sub2.tag)
              and sub1 is not None and dpg.is_item_shown(sub1.tag))

        # Keyboard: reopen, select group, Enter opens submenu, arrow down, Enter leaf.
        menu.hide()
        for _ in range(3):
            frame(view)
        menu.setActions(ITEM_MENU)
        menu.popup((40, 40))
        for _ in range(4):
            frame(view)
        menu._set_active_action("new_group")
        handled = menu._handle_key(dpg.mvKey_Right) if hasattr(dpg, "mvKey_Right") else None
        for _ in range(4):
            frame(view)
        sub2 = menu._submenus.get("new_group")
        check("Right key opens submenu", sub2 is not None and dpg.is_item_shown(sub2.tag),
              handled)
        mv_key_down = menu.backend.mvKey_Down
        menu._handle_key(mv_key_down)
        for _ in range(3):
            frame(view)
        check("second child active after Down",
              sub2._active_action == "command:new_file", sub2._active_action)
        triggered.clear()
        menu._handle_key(menu.backend.mvKey_Return)
        for _ in range(4):
            frame(view)
        check("Enter on leaf triggers", triggered == ["command:new_file"], triggered)

        # Disabled group: "Check ODB" is disabled; hovering must not crash or open.
        menu.popup((40, 40))
        for _ in range(4):
            frame(view)
        menu._row_hovered(user_data="check_odb_local")
        for _ in range(4):
            frame(view)
        check("disabled group stays inactive", menu._active_action != "check_odb_local",
              menu._active_action)

        print("RESULT", "OK" if not failures else "FAILED")
        return 0 if not failures else 1
    except Exception:
        traceback.print_exc()
        print("RESULT EXCEPTION")
        return 1
    finally:
        if menu is not None:
            try:
                menu.hide()
            except Exception:
                pass
        dpg.destroy_context()


if __name__ == "__main__":
    sys.exit(main())
