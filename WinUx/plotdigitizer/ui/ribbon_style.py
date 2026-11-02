"""Plot Digitizer's uniform command-tile geometry (not a global ribbon change)."""
from dataclasses import replace
import os
from pathlib import Path
from DearUIQt.ribbon.display_templates import get_ribbon_display_template
from DearUIQt.core import QItemInputBinding
from DearUIQt.widgets import QRetainedItem, QMenu
from DearUIQt.gui import QtFusionPalette, QFontDatabase, QFontMetrics
from DearUIQt.themes import ThemeTarget, ThemeColor, ThemeStyle, make_theme, theme_component
from DearUIQt.ribbon.textures import RibbonTileTextures
from ...ui.ribbon import RibbonBar


DIGITIZER_RIBBON_DISPLAY = replace(get_ribbon_display_template("compact"),
    key="plot-digitizer", name="Plot Digitizer",
    # Groups reserve 10 px outside their content. 64 px dropdown tiles plus
    # top inset, caption gap and a full text row no longer fit a 92 px body.
    tab_height=30, body_height=108, group_footer_height=18,
    # Keep all point commands, including Delete, visible at the 1100 px minimum width.
    # Select Plot reserves a wider tile explicitly for its longer label.
    large_button_width=64, large_button_height=64, large_icon_size=28,
    large_label_height=20, tile_font_size=11, tile_line_height=14,
    # Keep the workflow groups visible without clipping the final Settings
    # command at the 1100 px minimum. Retain full-size icons/command tiles;
    # reclaim the redundant horizontal padding around each group instead.
    tile_text_margin=5, command_gap=3, group_gap=2,
    group_horizontal_padding=1, controls_horizontal_padding=1,
    button_rounding=4,
)


class DigitizerRibbonMenu(QMenu):
    """Larger ribbon-only popup rows, without changing other WinUx menus."""

    ROW_HEIGHT = 36
    ICON_SIZE = 24
    ICON_SLOT = 34
    ICON_Y_NUDGE = 0
    ROW_PAD_X = 6
    LABEL_PAD = 8
    FONT_SIZE = 16

    def __init__(self, *args, menu_font=None, **kwargs):
        self._menu_font = menu_font
        super().__init__(*args, **kwargs)
        # Ribbon popups use a light 1 px outline rather than QMenu's default
        # dark 2 px border/shadow. Other application menus remain unchanged.
        p = QtFusionPalette
        surface = make_theme(theme_component(ThemeTarget.ALL,
            colors={ThemeColor.WINDOW_BACKGROUND: p.WINDOW,
                    ThemeColor.CHILD_BACKGROUND: p.WINDOW,
                    ThemeColor.POPUP_BACKGROUND: p.WINDOW,
                    ThemeColor.TEXT: p.TEXT, ThemeColor.TEXT_DISABLED: p.TEXT_DISABLED,
                    ThemeColor.SEPARATOR: p.BORDER_LIGHT, ThemeColor.BORDER: p.BORDER_LIGHT,
                    ThemeColor.BORDER_SHADOW: (0, 0, 0, 0)},
            styles={ThemeStyle.WINDOW_PADDING: (self.WINDOW_PAD_X, self.WINDOW_PAD_Y),
                    ThemeStyle.ITEM_SPACING: (0, 0), ThemeStyle.WINDOW_BORDER_SIZE: 1,
                    ThemeStyle.CHILD_BORDER_SIZE: 1, ThemeStyle.WINDOW_ROUNDING: 2,
                    ThemeStyle.CHILD_ROUNDING: 2, ThemeStyle.POPUP_ROUNDING: 2}),
            backend=self.backend, tag='winux.plotdigitizer.ribbon.menu.surface', cache=True)
        self.backend.bind_item_theme(self.tag, surface)

    def _measure_text(self, text):
        if self._menu_font is not None:
            size = QFontMetrics(self._menu_font, backend=self.backend).size(str(text or 'Ag'))
            return size.width(), size.height()
        return super()._measure_text(text)

    def _build_row(self, spec, width):
        super()._build_row(spec, width)
        if spec.get('separator') or self._menu_font is None:
            return
        key = str(spec.get('action') or spec.get('id') or '')
        items = self._items[key]
        # Native text participates in the popup's normal paint path. A custom
        # draw-list label can disappear on secondary native menu surfaces.
        for item in (items['label'], items.get('shortcut')):
            if item is not None:
                self.backend.bind_item_font(item, self._menu_font.nativeId())


class DigitizerRibbonBar(RibbonBar):
    """Align group captions to rendered commands, not estimated text widths."""

    TILE_BOTTOM_PADDING = 10
    NORMALIZE_ICON_BOUNDS = True
    COMMAND_TOP_INSET = 5
    CAPTION_GAP = 2
    MENU_ARROW_HEIGHT = 10

    def _tile_texture(self, record):
        disabled = not bool(record.get('enabled', True))
        return RibbonTileTextures.get(
            record.get('image'), record.get('label', ''),
            int(record.get('width') or self.LARGE_BUTTON_WIDTH),
            self.LARGE_BUTTON_HEIGHT, self.LARGE_ICON_SIZE,
            font_size=self.TILE_FONT_SIZE, line_height=self.TILE_LINE_HEIGHT,
            text_margin=self.TILE_TEXT_MARGIN,
            text_color=self.visual_style.disabled_text if disabled else self.visual_style.text,
            icon_path_resolver=self.icon_path_resolver, backend=self.backend,
            bottom_padding=self.TILE_BOTTOM_PADDING,
            normalize_icon_bounds=self.NORMALIZE_ICON_BOUNDS, disabled=disabled,
            dropdown_indicator=bool(record.get('menu_indicator')))

    def add_menu_button(self, tab_key, group_key, key, label, entries, *, image=None,
                        enabled=True, tooltip=None):
        """Keep the complete icon tile but give its arrow a separate hit target."""
        actions, commands = [], {}
        for index, entry in enumerate(entries):
            if entry is None:
                actions.append({'separator': True, 'label': '---', 'action': 'sep_{}'.format(index)})
                continue
            spec = dict(entry)
            callback = spec.pop('callback', None)
            action = str(spec.get('action') or spec['id'])
            spec['action'] = action
            actions.append(spec)
            if callable(callback):
                commands[action] = (callback, spec)
        menu = DigitizerRibbonMenu(actions, backend=self.backend, parent=self, menu_font=self._ribbon_menu_font(),
                                   min_width=260, max_width=460)
        self._menus.append(menu)
        record = self._new_button_record(tab_key, group_key, key, label,
                                        lambda: self._repeat_menu_action(key),
                                        checkable=False, checked=False, enabled=enabled)
        width = self.LARGE_BUTTON_WIDTH
        record.update(size='large', image=image, menu=menu, split=True, tile_split=True,
                      menu_indicator=True, width=width, uses_template_width=True,
                      menu_commands=commands, current_action=next(iter(commands)), tooltip=tooltip)
        group = self._groups[(str(tab_key), str(group_key))]
        container = self.backend.add_child_window(parent=group['row'], width=width,
            height=self.LARGE_BUTTON_HEIGHT, border=False, no_scrollbar=True, no_scroll_with_mouse=True)
        with self.backend.theme() as surface:
            with self.backend.theme_component(self.backend.mvAll):
                self.backend.add_theme_style(self.backend.mvStyleVar_WindowPadding, 0, 0)
                self.backend.add_theme_style(self.backend.mvStyleVar_ItemSpacing, 0, 0)
                self.backend.add_theme_color(self.backend.mvThemeCol_ChildBg, (0, 0, 0, 0))
        self.backend.bind_item_theme(container, surface)
        texture = self._tile_texture(record)
        boundary = (self.LARGE_BUTTON_HEIGHT - self.MENU_ARROW_HEIGHT) / self.LARGE_BUTTON_HEIGHT
        main = self.backend.add_image_button(texture, parent=container, width=width,
            height=self.LARGE_BUTTON_HEIGHT - self.MENU_ARROW_HEIGHT, uv_min=(0, 0), uv_max=(1, boundary),
            background_color=(0, 0, 0, 0), enabled=enabled,
            callback=lambda *_: self._button_clicked(key))
        arrow = self.backend.add_image_button(texture, parent=container, width=width,
            height=self.MENU_ARROW_HEIGHT, uv_min=(0, boundary), uv_max=(1, 1),
            background_color=(0, 0, 0, 0), enabled=enabled,
            callback=lambda *_: self._open_repeat_menu(key))
        record.update(tag=main, image_tag=main, arrow=arrow, container=container,
                      layout_slot=container, items=[main, arrow], tile_texture=texture,
                      large_tile=True, large_image=True)
        self._buttons[str(key)] = record
        self._reserve_group_width(group, container, width)
        self._refresh_button_theme(str(key))
        hint = self._add_tooltip(main, '{}\nClick the arrow to choose another command.'.format(tooltip or label))
        children = self.backend.get_item_children(hint, 1) if hint is not None else []
        record['current_tooltip_text'] = children[0] if children else None
        self._add_tooltip(arrow, 'Choose a command; the last selection becomes the main action.')
        menu.triggered.connect(lambda action, _context=None: self._select_menu_action(key, action))
        return main

    def _ribbon_menu_font(self):
        if not hasattr(self, '_menu_font_database'):
            self._menu_font_database = QFontDatabase(parent=self, backend=self.backend)
            self._menu_font = None
            fonts = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
            for path in (fonts / 'segoeui.ttf', fonts / 'arial.ttf',
                         Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')):
                self._menu_font = self._menu_font_database.addApplicationFont(path, DigitizerRibbonMenu.FONT_SIZE)
                if self._menu_font is not None:
                    break
        return self._menu_font

    def _open_repeat_menu(self, key):
        record = self._buttons[str(key)]
        if record.get('enabled', True):
            self._popup_menu(key, record['menu'], anchor=record['container'])

    def _repeat_menu_action(self, key):
        record = self._buttons[str(key)]
        self._select_menu_action(key, record['current_action'])

    def _select_menu_action(self, key, action):
        record = self._buttons[str(key)]
        command = record['menu_commands'].get(str(action))
        spec = record['menu']._find_spec(str(action))
        if (not record.get('enabled', True) or command is None or spec is None or
                not spec.get('enabled', True) or not spec.get('visible', True)):
            return
        callback, display = command
        record['current_action'] = str(action)
        record['label'] = display.get('ribbon_label', display['label'])
        record['image'] = display.get('ribbon_image', record['image'])
        if record.get('current_tooltip_text') is not None:
            self.backend.set_value(record['current_tooltip_text'],
                '{}\nClick to repeat. Click the arrow to choose another command.'.format(display['label']))
        self._refresh_button_theme(str(key))
        callback()

    def _refresh_button_theme(self, key):
        super()._refresh_button_theme(key)
        record = self._buttons.get(str(key))
        if record and record.get('tile_split'):
            self.backend.configure_item(record['arrow'], texture_tag=record['tile_texture'])
            self.backend.bind_item_theme(record['arrow'], self._image_button_theme(
                checked=False, disabled=not record.get('enabled', True)))

    def _apply_button_display_geometry(self, record):
        super()._apply_button_display_geometry(record)
        if record.get('tile_split'):
            width = record['width']
            self.backend.configure_item(record['container'], width=width, height=self.LARGE_BUTTON_HEIGHT)
            self.backend.configure_item(record['tag'], width=width,
                                        height=self.LARGE_BUTTON_HEIGHT - self.MENU_ARROW_HEIGHT)
            self.backend.configure_item(record['arrow'], width=width, height=self.MENU_ARROW_HEIGHT)

    def add_group(self, tab_key, key, label, **kwargs):
        tag = super().add_group(tab_key, key, label, **kwargs)
        group = self._groups[(str(tab_key), str(key))]
        # Native child surfaces do not apply ImGui WindowPadding. The width
        # allocator still reserves that padding, leaving it all on the right
        # unless the command row has an explicit inset on this hosting path.
        self.backend.configure_item(group["row"], pos=(
            self.GROUP_HORIZONTAL_PADDING + self.CONTROLS_HORIZONTAL_PADDING + 1,
            self.COMMAND_TOP_INSET))
        command_bottom = self.COMMAND_TOP_INSET + self.LARGE_BUTTON_HEIGHT
        self.backend.configure_item(group["controls"], height=command_bottom)
        self.backend.configure_item(group["footer_row"], pos=(0, command_bottom + self.CAPTION_GAP))
        # The outer ribbon may be a native child with no DPG visible callback.
        # Text is a rendered item on both native and embedded hosting paths.
        group["caption_alignment"] = QItemInputBinding(
            QRetainedItem(group["footer"], backend=self.backend), parent=self).onVisible(
                lambda *_args: self._align_command_captions()).activate()
        return tag

    def _align_command_captions(self, *_args):
        if self.is_minimized():
            return
        frame = self.backend.get_frame_count()
        if getattr(self, "_caption_alignment_frame", None) == frame:
            return
        self._caption_alignment_frame = frame
        for (tab, key), group in self._groups.items():
            if tab != self.active_tab() or not group.get("visible", True):
                continue
            commands = [record for record in self._buttons.values()
                        if record.get("tab") == tab and record.get("group") == key
                        and record.get("visible", True)]
            if not commands:
                continue
            rectangles = [QRetainedItem(record.get('container') or record["tag"], backend=self.backend).globalGeometry()
                          for record in commands]
            caption = QRetainedItem(group["footer"], backend=self.backend).globalGeometry()
            if caption.width() <= 0 or any(rect.width() <= 0 for rect in rectangles):
                continue  # Wait for the first presented frame / font metrics.
            # Native horizontal groups have a minimum control-height and center
            # text inside it. Position the visible caption, not that row's box.
            bottom = max(rect.y() + rect.height() for rect in rectangles)
            vertical_delta = round(bottom + self.CAPTION_GAP - caption.y())
            if vertical_delta:
                row = QRetainedItem(group["footer_row"], backend=self.backend).globalGeometry()
                panel = QRetainedItem(group["tag"], backend=self.backend).globalGeometry()
                self.backend.configure_item(group["footer_row"], pos=(
                    0, row.y() - panel.y() + vertical_delta))
            left = min(rect.x() for rect in rectangles)
            right = max(rect.x() + rect.width() for rect in rectangles)
            delta = round((left + right - caption.width()) / 2 - caption.x())
            if delta:
                spacer = group["footer_spacer"]
                width = self.backend.get_item_configuration(spacer).get("width", 0)
                self.backend.configure_item(spacer, width=max(0, int(width) + delta))
