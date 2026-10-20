"""Layout ownership for :class:`ExplorerListView`.

Extracted without changing geometry/timing behavior so the main Explorer facade
remains small while resize, coalesced relayout and frame-watch behavior stay in
one reusable owner.
"""
from __future__ import annotations

from DearUIQt import QGuiRuntime
from DearUIQt.core import QItemInputBinding
from DearUIQt.gui import QFontMetrics
from DearUIQt.widgets import QRetainedItem
from ...platform.windows_icons import ICON_SIZE


class ExplorerLayoutMixin:


    def _install_auto_width_geometry_handlers(self):
        """Keep Auto Width synchronized from retained item geometry events."""
        for binding in getattr(self, "_auto_width_geometry_registries", ()): 
            try:
                binding.delete()
            except Exception:
                pass
        self._auto_width_geometry_registries = []

        def bind_geometry_handler(item, suffix):
            retained = QRetainedItem(item) if item else None
            if retained is None or not retained.exists():
                return
            try:
                binding = (
                    QItemInputBinding(item)
                    .onResize(self._on_auto_width_geometry_event)
                    .onVisible(self._on_auto_width_geometry_event)
                    .activate()
                )
                self._auto_width_geometry_registries.append(binding)
            except Exception:
                pass

        bind_geometry_handler(self.window_tag, "pane")
        bind_geometry_handler(self.body_window, "body")

    def _on_auto_width_geometry_event(self, sender=None, app_data=None, user_data=None):
        """Refit visible sections when the live ListView width changes."""
        if not self.auto_width_enabled:
            return
        if not QRetainedItem(self.body_window).exists():
            return
        try:
            available = float(self._available_width())
        except Exception:
            return
        if available <= 20.0:
            return

        visible = self._visible_columns()
        if not visible:
            return
        total = sum(
            float(self._column_widths.get(c["key"], self.MIN_COLUMN_WIDTH))
            for c in visible
        )
        # visible-handler callbacks can occur every frame.  Only redraw when
        # the viewport or the column sum is actually out of sync.
        if (
            abs(available - float(self._last_available_width)) < 0.5
            and abs(available - total) < 0.5
        ):
            return

        self._ensure_column_widths(force=not bool(self._column_widths))
        self._fit_columns_auto_width(available)
        self._last_available_width = available
        self._text_fit_cache.clear()
        self._layout_all()
        try:
            self._update_native_cursor_geometry()
        except Exception:
            pass

    def resize(self, width=-1, height=-1):
        """Fit the ListView pane to its owner without creating outer scrolling."""
        if not QRetainedItem(self.window_tag).exists():
            return
        cfg = {}
        if width is not None:
            cfg["width"] = int(width) if float(width) > 0 else -1
        if height is not None:
            cfg["height"] = max(1, int(height)) if float(height) > 0 else -1
        QRetainedItem(self.window_tag).configure(**cfg)
        self._text_fit_cache.clear()
        self._resize_layout_pending = True
        try:
            if self.auto_width_enabled:
                self._sync_auto_width_to_viewport()
            self._layout_all()
        except Exception:
            pass

        # DearPyGui applies fill-width (-1) and splitter/container geometry on
        # the next rendered frame. Re-sync once the live child viewport has its
        # new size so Auto Width follows every ListView/container resize.
        if self.auto_width_enabled:
            def _sync_after_resize(sender=None, app_data=None):
                if not QRetainedItem(self.window_tag).exists():
                    return
                try:
                    self._sync_auto_width_to_viewport(layout=True)
                    self._update_native_cursor_geometry()
                except Exception:
                    pass
            try:
                QGuiRuntime().invokeNextFrame(_sync_after_resize)
            except Exception:
                pass
        overlay = getattr(self, "_scroller_arrow_overlay", None)
        if overlay is not None:
            overlay.update()

    def _queue_layout(self):
        """Coalesce many mouse-drag events into at most one layout per frame."""
        if self._resize_layout_pending:
            return
        self._resize_layout_pending = True

        def apply_layout():
            self._resize_layout_pending = False
            if QRetainedItem(self.header_canvas).exists():
                self._layout_all()

        try:
            QGuiRuntime().invokeNextFrame(apply_layout)
        except Exception:
            apply_layout()

    def _layout_all(self):
        """Lay out headers and rows using stable font and pixel measurements."""
        # Any direct layout also satisfies a previously queued layout request.
        # Keeping this flag set made later drag events silently skip redraws.
        self._resize_layout_pending = False
        if not QRetainedItem(self.header_canvas).exists():
            return

        geometry = self._column_geometry()
        total_width = sum(
            width
            for _, width in geometry.values()
        )
        self._layout_pinned_row()

        try:
            viewport_width, viewport_height = map(
                float, QRetainedItem(self.body_window).globalGeometry().size().toTuple()
            )
        except Exception:
            viewport_width = 0.0
            viewport_height = 0.0

        body_height = max(
            self.ROW_HEIGHT,
            len(self.items) * self.ROW_HEIGHT,
            viewport_height,
        )

        # Keep the body drawlist at least as large as the visible viewport.
        # Previously it stopped at the last data column, so a rubber-band
        # rectangle was clipped as soon as the pointer entered the blank area
        # on the right.  Explorer lets the gesture start and remain visible
        # anywhere inside the body, while horizontal scrolling still works when
        # the columns are wider than the viewport.
        body_width = max(
            total_width,
            max(1.0, viewport_width - 1.0),
        )

        # The body child reports the scrollable *content* viewport, which on
        # Dear ImGui/DPG excludes the vertical scrollbar strip whenever that
        # scrollbar is visible.  The QHeaderView-like header, however, belongs
        # to the outer ListView frame and must visually span the full frame.
        # Using only body_window here left a white strip at the right edge
        # (roughly the scrollbar width) even when Auto Width was enabled.
        try:
            pane_width = float(QRetainedItem(self.window_tag).globalGeometry().width())
        except Exception:
            pane_width = 0.0
        header_viewport_width = max(
            1.0,
            (pane_width - 2.0) if pane_width > 2.0 else (viewport_width - 1.0),
        )
        header_width = max(total_width, header_viewport_width)
        QRetainedItem(self.header_canvas).configure(
            width=max(1, int(round(header_width))),
            height=self.HEADER_HEIGHT,
        )

        # Resize the painted header background together with the drawlist.
        # Auto Width may change ``header_width`` after the primitive was first
        # created, and a drawlist does not automatically resize its children.
        # Painting to the full viewport keeps one uniform QHeaderView-style
        # grey across columns and any transient remainder at the right edge.
        header_background = getattr(self, "_header_background", None)
        if header_background and QRetainedItem(header_background).exists():
            QRetainedItem(header_background).configure(
                pmin=(0, 0),
                pmax=(header_width, self.HEADER_HEIGHT),
                fill=self.theme_config["header_bg"],
                color=self.theme_config["header_bg"],
                thickness=0.0,
            )

        QRetainedItem(self.body_canvas).configure(
            width=max(1, int(round(body_width))),
            height=max(1, int(round(body_height))),
        )
        overlay = getattr(self, "_scroller_arrow_overlay", None)
        if overlay is not None:
            overlay.update()

        # Render every row across the full logical canvas.
        self._sync_virtual_rows()

        body_font = self._fonts.get("body")
        header_font = self._fonts.get("header")

        # ------------------------------ header ------------------------------
        visible_columns = self._visible_columns()
        last_visible_key = visible_columns[-1]["key"] if visible_columns else None
        for column in visible_columns:
            key = column["key"]
            column_x, column_width = geometry[key]

            parts = self._header_items.get(key)
            if not parts:
                continue

            background = parts.get("background")
            if background and QRetainedItem(background).exists():
                # QHeaderView paints the final section through the header's
                # scrollbar-reserved strip.  Keep the logical/data width tied
                # to the body viewport so values are never hidden beneath the
                # vertical scrollbar; only the final header surface consumes
                # this visual remainder.
                section_right = column_x + column_width
                if key == last_visible_key:
                    section_right = max(section_right, header_width)
                QRetainedItem(background).configure(
                    pmin=(column_x, 0),
                    pmax=(section_right, self.HEADER_HEIGHT),
                )

            raw_label = column["label"]
            sorted_column = self.sort_key == key
            # QHeaderView reserves only the sub-control space it actually
            # needs.  The old fixed 48 px deduction made short Job Viewer
            # sections truncate far too early, especially Status/Tokens.
            right_reserve = 24.0 if sorted_column else 14.0
            label = self._fit_text(
                raw_label,
                max(0.0, column_width - right_reserve),
                header_font,
                16,
            )

            label_width, label_height = self._measure_text(
                label,
                header_font,
                16,
            )

            arrow_width = 7.0
            arrow_height = 5.0

            header_alignment = self.theme_config.get("header_alignment", "center")
            if header_alignment == "column":
                header_alignment = column.get("header_align", column.get("align", "left"))
            if header_alignment == "right":
                label_x = column_x + max(4.0, column_width - label_width - 18.0)
            elif header_alignment in ("center", "middle"):
                label_x = column_x + max(3.0, (column_width - label_width) * 0.5)
            else:
                # Native Windows/WinSCP details headers are left aligned for
                # text columns, with enough inset to visually separate them
                # from the resize divider.
                label_x = column_x + 7.0

            label_y = max(
                2.0,
                (self.HEADER_HEIGHT - label_height) * 0.5,
            )

            indicator_mode = self.theme_config.get("sort_indicator_mode", "edge")
            if sorted_column and indicator_mode == "inline":
                # Legacy Job Viewer: center label and sort marker as one visual
                # group.  Generic file details views keep the edge marker.
                combined_width = label_width + 5.0 + arrow_width
                label_x = column_x + max(3.0, (column_width - combined_width) * 0.5)
                indicator_x = label_x + label_width + 5.0
            else:
                indicator_x = column_x + column_width - arrow_width - 8.0
            indicator_y = (self.HEADER_HEIGHT - arrow_height) * 0.5

            # Snap draw origins to whole pixels. Text drawn at fractional
            # coordinates can look uneven due to glyph rasterization.
            label_x = float(round(label_x))
            label_y = float(round(label_y))
            indicator_x = float(round(indicator_x))
            indicator_y = float(round(indicator_y))

            QRetainedItem(parts["label"]).configure(
                pos=(label_x, label_y),
                text=label,
            )

            # Keep hidden markers laid out too: a header click reveals its
            # triangle immediately, before the deferred row refresh.
            cx = indicator_x + arrow_width * 0.5
            if self.sort_ascending:
                p1 = (indicator_x, indicator_y + arrow_height)
                p2 = (indicator_x + arrow_width, indicator_y + arrow_height)
                p3 = (cx, indicator_y)
            else:
                p1 = (indicator_x, indicator_y)
                p2 = (indicator_x + arrow_width, indicator_y)
                p3 = (cx, indicator_y + arrow_height)
            QRetainedItem(parts["indicator"]).configure( p1=p1, p2=p2, p3=p3, show=sorted_column)

            separator_x = column_x + column_width - 0.5

            QRetainedItem(parts["separator"]).configure(
                p1=(separator_x, 0),
                p2=(separator_x, self.HEADER_HEIGHT),
            )

        if self._header_top_line and QRetainedItem(self._header_top_line).exists():
            QRetainedItem(self._header_top_line).configure( p1=(0, 0.5),
                p2=(header_width, 0.5))
        if self._header_bottom_line and QRetainedItem(self._header_bottom_line).exists():
            QRetainedItem(self._header_bottom_line).configure( p1=(0, self.HEADER_HEIGHT - 0.5),
                p2=(header_width, self.HEADER_HEIGHT - 0.5))

        self._update_header_cell_visuals()

        self._layout_materialized_rows(
            geometry=geometry,
            total_width=total_width,
        )

    def _layout_materialized_rows(self, geometry=None, total_width=None, indices=None):
        """Lay out only currently materialized body rows.

        All logical rows are materialized. Pure scrolling moves the existing
        canvas without needing to recreate or re-layout rows.
        """
        if not QRetainedItem(self.body_canvas).exists():
            return
        if geometry is None:
            geometry = self._column_geometry()
        if total_width is None:
            total_width = sum(width for _, width in geometry.values())
        visible_width = min(total_width, self._available_width())

        body_font = self._fonts.get("body")
        selected_indices = set(getattr(self, "selected", ()) or ())
        geometry_changed_selected = set()
        for row in self._row_items:
            index = row["index"]
            if indices is not None and index not in indices:
                continue
            if not (0 <= index < len(self.items)):
                continue

            y0 = index * self.ROW_HEIGHT
            y1 = y0 + self.ROW_HEIGHT

            row_spacing = max(0, int(getattr(self, "ROW_SPACING", 0)))
            top_inset = row_spacing // 2
            bottom_inset = row_spacing - top_inset
            row_bounds = (
                0,
                int(round(y0)) + top_inset,
                max(1, int(round(visible_width))),
                max(int(round(y0)) + top_inset + 1, int(round(y1)) - bottom_inset),
            )
            previous_bounds = row.get("bounds")
            row["bounds"] = row_bounds
            if previous_bounds != row_bounds and index in selected_indices:
                # The crisp selected surface owns a second inner fill. A
                # resize/maximize changes row geometry without changing the
                # selection set, so the normal incremental selection cache
                # would otherwise skip this row and leave the inner fill at
                # its old width.
                geometry_changed_selected.add(index)
            QRetainedItem(row["background"]).configure(
                pmin=(row_bounds[0], row_bounds[1]),
                pmax=(row_bounds[2], row_bounds[3]),
            )
            QRetainedItem(row["bottom"]).configure(
                p1=(0, y1 - 0.5),
                p2=(total_width, y1 - 0.5),
            )

            item = self.items[index]
            # Publish newly allocated primitives only with their final geometry.
            # Do not change visibility on later layouts: native rename may have
            # deliberately hidden the source label underneath its editor.
            visibility = {"show": True} if row.get("pending_layout") else {}
            for column in self._visible_columns():
                key = column["key"]
                column_x, column_width = geometry[key]
                text_tag = row["texts"].get(key)
                if not text_tag or not QRetainedItem(text_tag).exists():
                    continue

                raw_value = self._display_cell_value(item, key)
                left_inset = 24.0 if key == "name" else self.CELL_PADDING
                right_inset = self.CELL_PADDING
                available_text_width = max(
                    0.0, column_width - left_inset - right_inset
                )
                value = self._fit_text(
                    raw_value, available_text_width, body_font, 15
                )
                text_width, text_height = self._measure_text(
                    value, body_font, 15
                )

                cell_style = self._cell_styles.get((id(item), key), {})
                align = cell_style.get("align", column.get("align", "left"))
                if key == "name" or align == "left":
                    text_x = column_x + left_inset
                elif align in ("center", "middle"):
                    text_x = (
                        column_x
                        + left_inset
                        + max(0.0, (available_text_width - text_width) * 0.5)
                    )
                elif align == "right":
                    text_x = column_x + column_width - right_inset - text_width
                else:
                    text_x = column_x + left_inset

                valign = cell_style.get("valign", column.get("valign", "middle"))
                if valign == "top":
                    text_y = y0 + 2.0
                elif valign == "bottom":
                    text_y = y1 - text_height - 2.0
                else:
                    text_y = y0 + max(
                        1.0, (self.ROW_HEIGHT - text_height) * 0.5
                    )

                text_x = float(round(text_x))
                text_y = float(round(text_y))
                QRetainedItem(text_tag).configure(pos=(text_x, text_y), text=value, **visibility)

                if key == "name":
                    icon = row.get("icon")
                    if icon and QRetainedItem(icon).exists():
                        icon_y = float(
                            round(y0 + (self.ROW_HEIGHT - ICON_SIZE) * 0.5)
                        )
                        QRetainedItem(icon).configure(
                            pmin=(column_x + 4.0, icon_y),
                            pmax=(
                                column_x + 4.0 + ICON_SIZE,
                                icon_y + ICON_SIZE,
                            ),
                            **visibility,
                        )
            row["pending_layout"] = False

        selection_refresh_indices = set(geometry_changed_selected)
        if indices is not None:
            selection_refresh_indices.update(int(i) for i in indices if i is not None)
        self._update_selection_draws(indices=selection_refresh_indices)
        self._update_hover_state()

    def _install_layout_watch(self):
            """Watch each visible body independently of DPG's frame callback slot."""
            startup_layout_passes = 0
            font_layout_finalized = False

            def fonts_are_ready():
                """Return True when Dear PyGui can measure the actual bound fonts."""
                samples = (
                    ("body", "0123456789 ABC xyz"),
                    ("header", "Date modified"),
                )

                for font_key, sample in samples:
                    font = self._fonts.get(font_key)

                    try:
                        if font is not None and getattr(font, "exists", lambda: True)():
                            size = QFontMetrics(font).size(sample).toTuple()
                        else:
                            size = QFontMetrics().size(sample).toTuple()

                        if (
                            size is None
                            or len(size) < 2
                            or float(size[0]) <= 0.0
                            or float(size[1]) <= 0.0
                        ):
                            return False

                    except Exception:
                        return False

                return True

            def watch(sender=None, app_data=None, user_data=None):
                nonlocal startup_layout_passes
                nonlocal font_layout_finalized

                if not QRetainedItem(self.header_canvas).exists():
                    return

                # The native window is created after show_viewport(), so retry until
                # the genuine viewport HWND becomes available.
                if not self._native_cursor_hook_active:
                    self._install_native_cursor_hook()

                self._update_header_hover_state()
                self._update_resize_cursor()
                self._update_drag_cursor()
                self._maybe_handoff_drag_to_windows_shell()
                self._update_hover_state()
                overlay = getattr(self, "_scroller_arrow_overlay", None)
                if overlay is not None:
                    overlay.update()
                self._drain_pending_external_drops()

                available = self._available_width()

                # Handle viewport or parent resizing.
                if (
                    abs(available - self._last_available_width) >= 1.0
                    and self._resize_key is None
                ):
                    delta = available - self._last_available_width
                    visible_columns = self._visible_columns()

                    if visible_columns:
                        if self.auto_width_enabled:
                            self._fit_columns_auto_width(available)
                        else:
                            fit_column = self._auto_fit_column(visible_columns)
                            fit_key = fit_column["key"]
                            fit_minimum = self._auto_fit_minimum(fit_key)
                            self._column_widths[fit_key] = max(
                                fit_minimum,
                                self._column_widths.get(
                                    fit_key, fit_minimum) + delta,
                            )

                    self._last_available_width = available
                    self._text_fit_cache.clear()
                    self._layout_all()

                # The first layout may have been calculated before the real font
                # metrics were available. Wait for at least two rendered frames and
                # then perform one clean layout using exact text dimensions.
                if not font_layout_finalized:
                    startup_layout_passes += 1

                    if startup_layout_passes >= 2 and fonts_are_ready():
                        font_layout_finalized = True

                        # Remove values produced using temporary fallback metrics.
                        self._text_fit_cache.clear()

                        # Recalculate available width because child-window dimensions
                        # are also unreliable before the viewport's first frame.
                        self._last_available_width = self._available_width()

                        if self.preserve_column_widths_on_startup:
                            # Preserve the specialized view's proportions as
                            # the basis, then Auto Width stretches those widths
                            # to the real viewport measured after startup.
                            self._ensure_column_widths(
                                force=not bool(self._column_widths)
                            )
                        else:
                            self._ensure_column_widths(force=True)
                        if self.auto_width_enabled:
                            self._sync_auto_width_to_viewport()
                        self._layout_all()
                        self._update_native_cursor_geometry()

            # Keep the existing layout/drag watch on its original surface.
            # Rename needs a drawable's visible state, but enabling this whole
            # watch there also changes drag/cursor/layout dispatch globally.
            try:
                binding = QItemInputBinding(self.body_window).onVisible(watch).activate()
                self._auto_width_geometry_registries.append(binding)
            except Exception:
                pass

            def watch_rename(sender=None, app_data=None, user_data=None):
                if self._rename_active:
                    self._process_inline_rename_focus()
                if self._pending_slow_rename is not None:
                    self._process_pending_slow_rename()

            try:
                binding = QItemInputBinding(self.body_canvas).onVisible(watch_rename).activate()
                self._auto_width_geometry_registries.append(binding)
            except Exception:
                pass

    def _header_local_x(self):
        _, local_x = self._header_mouse_position()
        return local_x

    def _scroller_content_size(self):
        """Measure logical columns/rows against the rendered content viewport."""
        rect = QRetainedItem(self.body_window).globalGeometry(clipped=True)
        if rect.isEmpty():
            return None
        width, height = rect.width(), rect.height()
        if width <= 0 or height <= 0:
            return None
        columns_width = sum(float(self._column_widths.get(c["key"], self.MIN_COLUMN_WIDTH))
                            for c in self._visible_columns())
        return (max(columns_width, max(1.0, width-1.0)),
                max(float(self.ROW_HEIGHT), len(self.items)*self.ROW_HEIGHT, height))
