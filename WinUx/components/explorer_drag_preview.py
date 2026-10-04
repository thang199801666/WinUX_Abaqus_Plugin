"""Lifecycle of the Explorer drag-preview draw layer."""
from __future__ import annotations
import dearpygui.dearpygui as dpg

class DragPreviewHelper:
    """Render an Explorer-like drag ghost and copy cursor above the viewport.

    The helper owns all temporary draw items used while files/folders are being
    dragged, keeping cursor/preview concerns out of :class:`ExplorerListView`.
    """

    MAX_VISIBLE_ITEMS = 3
    # Keep the ghost close to the pointer while leaving the hotspot visible.
    OFFSET_X = 9.0
    OFFSET_Y = 11.0

    def __init__(self, uid, body_font=None):
        self.uid = uid
        self.body_font = body_font
        self.active = False
        self.can_copy = False
        self.items = []
        self._drawlist = None
        self._parts = {}
        self.theme_config = {}
        # Do not create a viewport drawlist here. ExplorerListView is commonly
        # constructed before setup_dearpygui()/show_viewport(), and a viewport
        # drawlist created that early can exist in the registry without ever
        # being attached to the native viewport renderer. Build it lazily when
        # a real drag starts, after the viewport is alive.

    def _ensure_built(self):
        if self._drawlist and dpg.does_item_exist(self._drawlist):
            return True
        self._parts = {}
        tag = f"{self.uid}_drag_preview_layer"
        if dpg.does_item_exist(tag):
            try:
                dpg.delete_item(tag)
            except Exception:
                pass
        try:
            self._drawlist = dpg.add_viewport_drawlist(front=True, tag=tag)
        except TypeError:
            self._drawlist = dpg.add_viewport_drawlist(tag=tag)
        except Exception:
            self._drawlist = None
            return False

        parent = self._drawlist
        self._parts["shadow"] = dpg.draw_rectangle(
            (0, 0), (1, 1), parent=parent, fill=(0, 0, 0, 45),
            color=(0, 0, 0, 0), rounding=4, show=False,
        )
        self._parts["panel"] = dpg.draw_rectangle(
            (0, 0), (1, 1), parent=parent, fill=(255, 255, 255, 238),
            color=(170, 170, 170, 230), thickness=1, rounding=4, show=False,
        )
        self._parts["accent"] = dpg.draw_rectangle(
            (0, 0), (1, 1), parent=parent, fill=(0, 120, 215, 255),
            color=(0, 120, 215, 255), rounding=2, show=False,
        )
        self._parts["texts"] = []
        for _ in range(self.MAX_VISIBLE_ITEMS + 1):
            text = dpg.draw_text((0, 0), "", parent=parent,
                                 color=(25, 25, 25, 255), size=15, show=False)
            if self.body_font:
                try:
                    dpg.bind_item_font(text, self.body_font)
                except Exception:
                    pass
            self._parts["texts"].append(text)

        self.set_theme(self.theme_config)
        return True

    @staticmethod
    def _measure(text):
        try:
            size = dpg.get_text_size(text)
            return float(size[0]), float(size[1])
        except Exception:
            return float(len(text) * 7.5), 15.0

    def set_theme(self, config):
        self.theme_config = dict(config or {})
        if not self._parts:
            return
        mapping = {
            "panel": {"fill": self.theme_config.get("drag_bg", (255,255,255,238)), "color": self.theme_config.get("drag_border", (170,170,170,230))},
            "accent": {"fill": self.theme_config.get("drag_accent", (0,120,215,255)), "color": self.theme_config.get("drag_accent", (0,120,215,255))},
        }
        for key, values in mapping.items():
            tag = self._parts.get(key)
            if tag and dpg.does_item_exist(tag):
                dpg.configure_item(tag, **values)
        for tag in self._parts.get("texts", []):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, color=self.theme_config.get("drag_text", (25,25,25,255)))

    def begin(self, items):
        self.items = list(items)
        self.active = bool(self.items)
        self.can_copy = False
        if self.active and self._ensure_built():
            self.update(False)

    def update(self, can_copy, target_name=None):
        """Update the drag preview position and displayed information.

        Parameters
        ----------
        can_copy : bool
            True when the pointer is currently over a valid destination folder.

        target_name : str | None
            Display name of the destination folder. When supplied together with
            ``can_copy=True``, the preview changes from the dragged-item list to
            an Explorer-like action description:

                Copy "file.txt"
                To: "Destination"

            or:

                Copy 3 items
                To: "Destination"
        """
        if not self.active or not self._ensure_built():
            return

        self.can_copy = bool(can_copy)

        try:
            mx, my = map(float, dpg.get_mouse_pos(local=False))
        except Exception:
            return

        target_name = str(target_name or "").strip()

        # While hovering a valid destination folder, replace the normal file list
        # with an Explorer-like copy destination message.
        if self.can_copy and target_name:
            if len(self.items) == 1:
                source_name = str(self.items[0].name or "")

                names = [
                    f'Copy "{source_name}"',
                    f'To: "{target_name}"',
                ]
            else:
                names = [
                    f"Copy {len(self.items)} items",
                    f'To: "{target_name}"',
                ]

        # Outside a valid folder target, show the normal dragged-item preview.
        else:
            names = [
                str(item.name or "")
                for item in self.items[:self.MAX_VISIBLE_ITEMS]
            ]

            hidden_count = len(self.items) - self.MAX_VISIBLE_ITEMS
            if hidden_count > 0:
                names.append(f"+{hidden_count} more item(s)")

        # Ensure the preview panel always has at least one visible line.
        if not names:
            names = [""]

        # Truncate labels before measuring them so the calculated panel width
        # matches the actual rendered text.
        display_names = []
        for name in names:
            if len(name) > 42:
                name = name[:39] + "…"
            display_names.append(name)

        max_text_width = max(
            (self._measure(name)[0] for name in display_names),
            default=80.0,
        )

        width = min(
            330.0,
            max(150.0, max_text_width + 42.0),
        )

        height = 14.0 + max(1, len(display_names)) * 21.0

        x = mx + self.OFFSET_X
        y = my + self.OFFSET_Y

        dpg.configure_item(
            self._parts["shadow"],
            pmin=(x + 3.0, y + 3.0),
            pmax=(x + width + 3.0, y + height + 3.0),
            show=True,
        )

        dpg.configure_item(
            self._parts["panel"],
            pmin=(x, y),
            pmax=(x + width, y + height),
            show=True,
        )

        dpg.configure_item(
            self._parts["accent"],
            pmin=(x + 7.0, y + 8.0),
            pmax=(x + 11.0, y + height - 8.0),
            show=True,
        )

        text_tags = self._parts.get("texts", [])

        for index, tag in enumerate(text_tags):
            if index < len(display_names):
                dpg.configure_item(
                    tag,
                    pos=(x + 18.0, y + 7.0 + index * 21.0),
                    text=display_names[index],
                    show=True,
                )
            else:
                dpg.configure_item(tag, show=False)

        # The operating-system cursor remains controlled by the native
        # WM_SETCURSOR hook. This helper only renders the preview panel.

    def end(self):
        self.active = False
        self.can_copy = False
        self.items = []
        for key in ("shadow", "panel", "accent"):
            tag = self._parts.get(key)
            if tag and dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=False)
        for tag in self._parts.get("texts", []):
            if dpg.does_item_exist(tag):
                dpg.configure_item(tag, show=False)

    def destroy(self):
        self.end()
        if self._drawlist and dpg.does_item_exist(self._drawlist):
            dpg.delete_item(self._drawlist)


