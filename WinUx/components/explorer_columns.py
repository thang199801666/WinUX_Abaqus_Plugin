"""Column configuration and geometry behavior for ExplorerListView.

Kept separate from pointer/header gesture handling so column state can evolve
without growing the main Explorer widget facade.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

HORIZONTAL_ALIGNMENTS = ("left", "center", "right")
VERTICAL_ALIGNMENTS = ("top", "middle", "bottom")

def _normalize_alignment(value, allowed, default):
    value = str(value or default).lower()
    return value if value in allowed else default


class ExplorerColumnsMixin:
    def get_column(self, key):
        return next((c for c in self.columns if c["key"] == key), None)

    def set_columns(self, columns):
        self.columns = [dict(c) for c in columns]
        self._column_widths.clear(); self._ensure_column_widths(force=True); self._rebuild_draw_items()
        return self

    def add_column(self, key, label=None, align="left", valign="middle", weight=1.0, visible=True, index=None):
        if self.get_column(key):
            raise KeyError("Column already exists: %s" % key)
        column = {"key": key, "label": label or str(key), "align": _normalize_alignment(align, HORIZONTAL_ALIGNMENTS, "left"),
                  "valign": _normalize_alignment(valign, VERTICAL_ALIGNMENTS, "middle"), "weight": float(weight), "visible": bool(visible)}
        self.columns.insert(len(self.columns) if index is None else int(index), column)
        self._ensure_column_widths(force=True); self._rebuild_draw_items(); return self

    def remove_column(self, key):
        self.columns = [c for c in self.columns if c["key"] != key]
        self._column_widths.pop(key, None); self._rebuild_draw_items(); return self

    def set_column_visible(self, key, visible):
        column = self.get_column(key)
        if column is None:
            raise KeyError(key)
        visible = bool(visible)
        if not visible and column.get("visible", True):
            # A details view without any section has no useful header/body
            # geometry. Match Explorer/QHeaderView customizers and keep at
            # least one section visible.
            if len(self._visible_columns()) <= 1:
                return self
        column["visible"] = visible
        self._ensure_column_widths(force=False)
        if self.auto_width_enabled:
            self._fit_columns_auto_width(self._available_width())
        self._text_fit_cache.clear()
        self._rebuild_draw_items()
        self._last_available_width = self._available_width()
        return self

    def set_auto_width(self, enabled):
        self.auto_width_enabled = bool(enabled)
        if self.auto_width_enabled:
            self._sync_auto_width_to_viewport(layout=True)
        self._sync_header_context_menu_state()
        return self

    def auto_width(self):
        return bool(self.auto_width_enabled)

    def _sync_auto_width_to_viewport(self, locked_key=None, layout=False):
        """Synchronize visible section widths with the live ListView viewport.

        This is the single entry point used by startup, owner resizing and
        header-section resizing.  When Auto Width is checked, the visible
        columns must always consume exactly the current ListView width.
        """
        if not self.auto_width_enabled:
            return False
        available = float(self._available_width())
        self._ensure_column_widths(force=False)
        self._fit_columns_auto_width(available, locked_key=locked_key)
        self._last_available_width = available
        self._text_fit_cache.clear()
        if layout:
            self._layout_all()
        return True

    def set_column_width(self, key, width):
        if self.get_column(key) is None:
            raise KeyError(key)
        self._column_widths[key] = max(self.MIN_COLUMN_WIDTH, float(width))
        if self.auto_width_enabled:
            self._sync_auto_width_to_viewport(locked_key=key)
        self._layout_all()
        return self

    def set_column_alignment(self, key, horizontal=None, vertical=None):
        return self.set_column_style(key, align=horizontal, valign=vertical)

    def set_column_style(self, key, align=None, valign=None, label=None, weight=None):
        column = self.get_column(key)
        if column is None: raise KeyError(key)
        if align is not None: column["align"] = _normalize_alignment(align, HORIZONTAL_ALIGNMENTS, "left")
        if valign is not None: column["valign"] = _normalize_alignment(valign, VERTICAL_ALIGNMENTS, "middle")
        if label is not None: column["label"] = str(label)
        if weight is not None: column["weight"] = float(weight); self._column_widths.pop(key, None)
        self._ensure_column_widths(force=True); self._rebuild_draw_items(); return self

    def set_cell_value(self, item_or_index, column_key, value):
        item = self.items[item_or_index] if isinstance(item_or_index, int) else item_or_index
        self._cell_values[(id(item), column_key)] = value
        self._refresh_row_content(); self._layout_all(); return self

    def set_cell_alignment(self, item_or_index, column_key, horizontal=None, vertical=None):
        item = self.items[item_or_index] if isinstance(item_or_index, int) else item_or_index
        style = self._cell_styles.setdefault((id(item), column_key), {})
        if horizontal is not None: style["align"] = _normalize_alignment(horizontal, HORIZONTAL_ALIGNMENTS, "left")
        if vertical is not None: style["valign"] = _normalize_alignment(vertical, VERTICAL_ALIGNMENTS, "middle")
        self._layout_all(); return self

    def clear_cell_customization(self, item_or_index, column_key=None):
        item = self.items[item_or_index] if isinstance(item_or_index, int) else item_or_index
        keys = [k for k in set(self._cell_styles) | set(self._cell_values) if k[0] == id(item) and (column_key is None or k[1] == column_key)]
        for key in keys: self._cell_styles.pop(key, None); self._cell_values.pop(key, None)
        self._refresh_row_content(); self._layout_all(); return self

    def _visible_columns(self):
        return [column for column in self.columns if column.get("visible", True)]

    def _auto_fit_column(self, visible_columns=None):
        """Return the column that absorbs owner-width changes.

        Existing users retain the original behavior: when no explicit key is
        supplied, the last visible column remains the flexible column.
        """
        visible = visible_columns if visible_columns is not None else self._visible_columns()
        if not visible:
            return None
        if self.auto_fit_column_key is not None:
            for column in visible:
                if column["key"] == self.auto_fit_column_key:
                    return column
        return visible[-1]

    def _auto_fit_minimum(self, key):
        if key == self.auto_fit_column_key and self.auto_fit_min_width is not None:
            return self.auto_fit_min_width
        return float(self.MIN_COLUMN_WIDTH)

    def _available_width(self):
        """Return the actual visible ListView content width.

        Do not use ``header_canvas`` as the source of truth here.  Its width is
        derived from the current column sum in ``_layout_all``; reading it back
        makes Auto Width self-referential, so the columns can never discover a
        wider parent after a container resize.  The body child window tracks the
        real pane width and therefore matches the row/header viewport.
        """
        try:
            width = float(dpg.get_item_rect_size(self.body_window)[0])
            if width > 20:
                return width
        except Exception:
            pass
        try:
            width = float(dpg.get_item_rect_size(self.window_tag)[0]) - 2.0
            if width > 20:
                return width
        except Exception:
            pass
        return max(320.0, float(self.width if self.width and self.width > 0 else 800))

    def _ensure_column_widths(self, force=False):
        available = self._available_width()
        visible = self._visible_columns()
        if not visible:
            return
        if force or not self._column_widths:
            total_weight = sum(max(float(c.get("weight", 1.0)), 0.01) for c in visible)
            self._column_widths = {
                c["key"]: max(self.MIN_COLUMN_WIDTH, available * float(c.get("weight", 1.0)) / total_weight)
                for c in visible
            }
            self._fit_columns_to_width(available)
        else:
            for c in visible:
                self._column_widths.setdefault(c["key"], self.MIN_COLUMN_WIDTH)
        self._last_available_width = available

    def _fit_columns_to_width(self, available):
        """Fit visible sections to *available* pixels using current policy.

        The public/internal signature is intentionally unchanged for backward
        compatibility. Auto Width delegates to the proportional fitter; when
        disabled the historical single stretch-section behavior is retained.
        """
        if self.auto_width_enabled:
            return self._fit_columns_auto_width(available)
        visible = self._visible_columns()
        if not visible:
            return
        total = sum(self._column_widths.get(c["key"], self.MIN_COLUMN_WIDTH) for c in visible)
        delta = float(available) - total
        fit_column = self._auto_fit_column(visible)
        fit_key = fit_column["key"]
        fit_minimum = self._auto_fit_minimum(fit_key)
        self._column_widths[fit_key] = max(
            fit_minimum,
            self._column_widths.get(fit_key, fit_minimum) + delta,
        )

    def _fit_columns_auto_width(self, available, locked_key=None):
        """Proportionally stretch visible sections to exactly *available*.

        ``locked_key`` is used during interactive resize: the grabbed section
        keeps the requested width and all other visible sections absorb the
        complementary delta.
        """
        visible = self._visible_columns()
        if not visible:
            return
        available = max(1.0, float(available))
        keys = [c["key"] for c in visible]
        minimums = {key: float(self._auto_fit_minimum(key)) for key in keys}
        min_total = sum(minimums.values())
        if available <= min_total + 1e-6:
            each = available / float(len(keys))
            for key in keys:
                self._column_widths[key] = max(1.0, each)
            used = sum(self._column_widths[key] for key in keys[:-1])
            self._column_widths[keys[-1]] = max(1.0, available - used)
            return

        locked_key = locked_key if locked_key in keys else None
        free_keys = list(keys)
        remaining = available
        if locked_key is not None and len(keys) > 1:
            other_min = sum(minimums[k] for k in keys if k != locked_key)
            locked = min(
                max(minimums[locked_key], float(self._column_widths.get(locked_key, minimums[locked_key]))),
                max(minimums[locked_key], available - other_min),
            )
            self._column_widths[locked_key] = locked
            remaining -= locked
            free_keys.remove(locked_key)

        pending = list(free_keys)
        fixed = {}
        while pending:
            base_total = sum(max(1.0, float(self._column_widths.get(k, minimums[k]))) for k in pending)
            pool = max(0.0, remaining - sum(fixed.values()))
            newly_fixed = []
            for key in pending:
                basis = max(1.0, float(self._column_widths.get(key, minimums[key])))
                proposed = pool * basis / base_total if base_total > 0.0 else pool / len(pending)
                if proposed < minimums[key]:
                    fixed[key] = minimums[key]
                    newly_fixed.append(key)
            if not newly_fixed:
                for key in pending:
                    basis = max(1.0, float(self._column_widths.get(key, minimums[key])))
                    self._column_widths[key] = pool * basis / base_total if base_total > 0.0 else pool / len(pending)
                break
            pending = [k for k in pending if k not in newly_fixed]

        for key, value in fixed.items():
            self._column_widths[key] = value

        sink = next((k for k in reversed(keys) if k != locked_key), keys[-1])
        used = sum(float(self._column_widths.get(k, 0.0)) for k in keys)
        self._column_widths[sink] = max(1.0, self._column_widths[sink] + (available - used))

    def _column_geometry(self):
        x = 0.0
        geometry = {}
        for column in self._visible_columns():
            width = float(self._column_widths.get(column["key"], self.MIN_COLUMN_WIDTH))
            geometry[column["key"]] = (x, width)
            x += width
        return geometry

    def _auto_size_column_to_contents(self, key):
        """Resize one header section to its contents, like QHeaderView.

        The operation is intentionally explicit (double-click on a separator),
        so normal owner resizing still uses WinUx's configured stretch column.
        Very long filenames are capped to a practical desktop width while the
        horizontal scrollbar remains available for the full text.
        """
        column = next((c for c in self._visible_columns() if c.get("key") == key), None)
        if column is None:
            return False
        body_font = self._fonts.get("body")
        header_font = self._fonts.get("header")
        label = str(column.get("label") or key or "")
        header_width, _ = self._measure_text(label, header_font, fallback_size=16)
        required = header_width + float(self.CELL_PADDING) * 2.0 + 22.0

        # Measuring happens only on an explicit double click. Sampling up to
        # 2000 rows keeps large remote directories responsive while covering
        # realistic file lists accurately.
        rows = self.items[:2000]
        if self._pinned_item is not None:
            rows = [self._pinned_item] + list(rows)
        for item in rows:
            value = self._display_cell_value(item, key)
            width, _ = self._measure_text(value, body_font, fallback_size=15)
            extra = float(self.CELL_PADDING) * 2.0
            if key == "name":
                extra += 24.0  # icon + icon/text gap
            required = max(required, width + extra)

        available = max(320.0, float(self._available_width()))
        maximum = max(260.0, min(720.0, available * 0.72))
        width = max(float(self.MIN_COLUMN_WIDTH), min(float(required), maximum))
        self._column_widths[key] = width
        if self.auto_width_enabled:
            self._fit_columns_auto_width(available, locked_key=key)
        self._text_fit_cache.clear()
        self._layout_all()
        self._update_native_cursor_geometry()
        return True

    def _separator_at(self, local_x):
        # Use a generous invisible hit zone around each one-pixel separator.
        # The visible line remains thin, but grabbing it is as easy as Explorer.
        hit = max(8.0, float(self.SEPARATOR_HIT))
        x = 0.0
        for column in self._visible_columns():
            x += float(self._column_widths.get(column["key"], self.MIN_COLUMN_WIDTH))
            if not column.get("resizable", True):
                continue
            if abs(float(local_x) - x) <= hit:
                return column["key"]
        return None

    def _column_at(self, local_x):
        x = 0.0
        for column in self._visible_columns():
            width = self._column_widths[column["key"]]
            if x <= local_x < x + width:
                return column["key"]
            x += width
        return None
