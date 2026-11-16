"""Optional declarative *composition* templates for Ribbon content.

This module describes which tabs/groups/commands exist.  Visual geometry and
appearance live separately in :mod:`DearUIQt.ribbon.display_templates`; new
generic styling work should use ``RibbonDisplayTemplate`` rather than adding
application-specific menus here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

from .components import RibbonButton, RibbonGroup, RibbonTab


_COMMAND_KINDS = {"button", "menu", "split", "separator"}


@dataclass(frozen=True)
class RibbonCommandTemplate:
    """Declarative command inside a :class:`RibbonGroupTemplate`.

    ``action`` and ``menu`` are logical binding names.  When omitted, ``key`` is
    used, so most applications can simply provide dictionaries keyed by the same
    command identifiers used by the template.
    """

    key: str
    text: str = ""
    kind: str = "button"
    action: str | None = None
    menu: str | None = None
    size: str = "auto"
    width: int | None = None
    icon: str | None = None
    image: str | None = None
    checkable: bool = False
    checked: bool = False
    enabled: bool = True
    tooltip: str | None = None
    separator_width: int = 5

    def __post_init__(self):
        kind = str(self.kind or "button").strip().lower()
        if kind not in _COMMAND_KINDS:
            raise ValueError("Unsupported ribbon command kind {!r}.".format(self.kind))
        object.__setattr__(self, "kind", kind)
        if not str(self.key).strip():
            raise ValueError("Ribbon command template key cannot be empty.")

    @property
    def action_key(self) -> str:
        return str(self.action or self.key)

    @property
    def menu_key(self) -> str:
        return str(self.menu or self.key)


@dataclass(frozen=True)
class RibbonGroupTemplate:
    key: str
    text: str
    commands: tuple[RibbonCommandTemplate, ...] = field(default_factory=tuple)
    width: int = 160
    layout: str = "mixed"
    launcher_action: str | None = None
    launcher_tooltip: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "commands", tuple(self.commands))
        if not str(self.key).strip():
            raise ValueError("Ribbon group template key cannot be empty.")


@dataclass(frozen=True)
class RibbonTabTemplate:
    key: str
    text: str
    groups: tuple[RibbonGroupTemplate, ...] = field(default_factory=tuple)
    activate: bool = False

    def __post_init__(self):
        object.__setattr__(self, "groups", tuple(self.groups))
        if not str(self.key).strip():
            raise ValueError("Ribbon tab template key cannot be empty.")


@dataclass(frozen=True)
class RibbonTemplate:
    """Complete reusable ribbon composition preset."""

    key: str
    name: str
    tabs: tuple[RibbonTabTemplate, ...]
    description: str = ""
    density: str = "normal"
    quick_access: bool = False
    responsive: bool = True

    def __post_init__(self):
        object.__setattr__(self, "tabs", tuple(self.tabs))
        if not str(self.key).strip():
            raise ValueError("Ribbon template key cannot be empty.")
        if not self.tabs:
            raise ValueError("Ribbon template must contain at least one tab.")

        tab_keys = set()
        command_keys = set()
        for tab in self.tabs:
            if tab.key in tab_keys:
                raise ValueError("Duplicate ribbon tab key {!r}.".format(tab.key))
            tab_keys.add(tab.key)
            group_keys = set()
            for group in tab.groups:
                if group.key in group_keys:
                    raise ValueError(
                        "Duplicate ribbon group key {!r} in tab {!r}.".format(group.key, tab.key)
                    )
                group_keys.add(group.key)
                for command in group.commands:
                    if command.kind == "separator":
                        continue
                    if command.key in command_keys:
                        raise ValueError(
                            "Duplicate ribbon command key {!r}; command keys are global within a RibbonBar.".format(
                                command.key
                            )
                        )
                    command_keys.add(command.key)


@dataclass
class RibbonTemplateInstance:
    """Runtime objects produced while applying a template."""

    bar: object
    template: RibbonTemplate
    tabs: dict[str, RibbonTab] = field(default_factory=dict)
    groups: dict[tuple[str, str], RibbonGroup] = field(default_factory=dict)
    commands: dict[str, RibbonButton] = field(default_factory=dict)
    separators: list[object] = field(default_factory=list)

    def tab(self, key: str) -> RibbonTab | None:
        return self.tabs.get(str(key))

    def group(self, tab_key: str, group_key: str) -> RibbonGroup | None:
        return self.groups.get((str(tab_key), str(group_key)))

    def command(self, key: str) -> RibbonButton | None:
        return self.commands.get(str(key))


_TEMPLATES: dict[str, RibbonTemplate] = {}


def register_ribbon_template(template: RibbonTemplate, *, replace: bool = False) -> RibbonTemplate:
    """Register an application or library preset under its stable key."""
    if not isinstance(template, RibbonTemplate):
        raise TypeError("template must be a RibbonTemplate")
    key = str(template.key)
    if key in _TEMPLATES and not replace:
        raise ValueError("Ribbon template {!r} is already registered.".format(key))
    _TEMPLATES[key] = template
    return template


def get_ribbon_template(template: str | RibbonTemplate) -> RibbonTemplate:
    if isinstance(template, RibbonTemplate):
        return template
    key = str(template)
    try:
        return _TEMPLATES[key]
    except KeyError as exc:
        raise KeyError(
            "Unknown ribbon template {!r}. Available: {}".format(
                key, ", ".join(sorted(_TEMPLATES)) or "<none>"
            )
        ) from exc


def ribbon_template_names() -> tuple[str, ...]:
    return tuple(sorted(_TEMPLATES))


def _binding(mapping: Mapping[str, object] | None, key: str, default=None):
    if mapping is None:
        return default
    return mapping.get(str(key), default)


def apply_ribbon_template(
    bar,
    template: str | RibbonTemplate,
    *,
    actions: Mapping[str, Callable] | None = None,
    menus: Mapping[str, Iterable] | None = None,
    images: Mapping[str, str] | None = None,
    icons: Mapping[str, str] | None = None,
    disable_unbound: bool = False,
    responsive_width: int | None = None,
) -> RibbonTemplateInstance:
    """Populate an existing :class:`RibbonBar` from a declarative template.

    Resource maps override resources embedded in the template and are keyed by
    command key.  ``actions`` and ``menus`` may instead use the command's
    explicit logical binding name when one is provided.
    """
    spec = get_ribbon_template(template)
    result = RibbonTemplateInstance(bar=bar, template=spec)

    for tab_spec in spec.tabs:
        tab = bar.create_tab(tab_spec.key, tab_spec.text, activate=tab_spec.activate)
        result.tabs[tab_spec.key] = tab
        for group_spec in tab_spec.groups:
            launcher = _binding(actions, group_spec.launcher_action) if group_spec.launcher_action else None
            group = tab.add_group(
                group_spec.key,
                group_spec.text,
                width=group_spec.width,
                layout=group_spec.layout,
                launcher=launcher,
                launcher_tooltip=group_spec.launcher_tooltip,
            )
            result.groups[(tab_spec.key, group_spec.key)] = group

            for command_spec in group_spec.commands:
                if command_spec.kind == "separator":
                    result.separators.append(
                        group.add_separator(width=command_spec.separator_width)
                    )
                    continue

                callback = _binding(actions, command_spec.action_key)
                entries = _binding(menus, command_spec.menu_key, ())
                image = _binding(images, command_spec.key, command_spec.image)
                icon = _binding(icons, command_spec.key, command_spec.icon)
                if command_spec.kind == "menu":
                    bound = bool(entries)
                elif command_spec.kind == "split":
                    bound = callback is not None or bool(entries)
                else:
                    bound = callback is not None
                enabled = bool(command_spec.enabled and (bound or not disable_unbound))
                common = dict(
                    size=command_spec.size,
                    width=command_spec.width,
                    icon=icon,
                    image=image,
                    enabled=enabled,
                    tooltip=command_spec.tooltip,
                )
                if command_spec.kind == "menu":
                    command = group.add_menu_button(
                        command_spec.key, command_spec.text, entries, **common
                    )
                elif command_spec.kind == "split":
                    command = group.add_split_button(
                        command_spec.key, command_spec.text, callback, entries, **common
                    )
                else:
                    command = group.add_button(
                        command_spec.key,
                        command_spec.text,
                        callback,
                        checkable=command_spec.checkable,
                        checked=command_spec.checked,
                        **common,
                    )
                result.commands[command_spec.key] = command

    if spec.responsive:
        bar.set_responsive(True, width=responsive_width)
    return result


def create_ribbon_from_template(
    parent,
    template: str | RibbonTemplate,
    *,
    actions: Mapping[str, Callable] | None = None,
    menus: Mapping[str, Iterable] | None = None,
    images: Mapping[str, str] | None = None,
    icons: Mapping[str, str] | None = None,
    disable_unbound: bool = False,
    responsive_width: int | None = None,
    ribbon_kwargs: Mapping[str, object] | None = None,
) -> RibbonTemplateInstance:
    """Create a RibbonBar with a preset's recommended density and QAT state."""
    from .bar import RibbonBar

    spec = get_ribbon_template(template)
    options = {
        "density": spec.density,
        "quick_access": spec.quick_access,
    }
    options.update(dict(ribbon_kwargs or {}))
    bar = RibbonBar(parent, **options)
    return apply_ribbon_template(
        bar,
        spec,
        actions=actions,
        menus=menus,
        images=images,
        icons=icons,
        disable_unbound=disable_unbound,
        responsive_width=responsive_width,
    )


class RibbonTemplateFactory:
    """Qt-style factory facade for the template registry."""

    @staticmethod
    def names() -> tuple[str, ...]:
        return ribbon_template_names()

    @staticmethod
    def get(template: str | RibbonTemplate) -> RibbonTemplate:
        return get_ribbon_template(template)

    @staticmethod
    def register(template: RibbonTemplate, *, replace: bool = False) -> RibbonTemplate:
        return register_ribbon_template(template, replace=replace)

    @staticmethod
    def apply(bar, template: str | RibbonTemplate, **bindings) -> RibbonTemplateInstance:
        return apply_ribbon_template(bar, template, **bindings)

    @staticmethod
    def create(parent, template: str | RibbonTemplate, **bindings) -> RibbonTemplateInstance:
        return create_ribbon_from_template(parent, template, **bindings)


# ---------------------------------------------------------------- presets

def _cmd(key, text, *, kind="button", size="auto", width=None, tooltip=None,
         checkable=False, checked=False):
    return RibbonCommandTemplate(
        key, text, kind=kind, size=size, width=width, tooltip=tooltip,
        checkable=checkable, checked=checked,
    )


def _sep(key):
    return RibbonCommandTemplate(key, kind="separator")


OFFICE_DATA_TEMPLATE = RibbonTemplate(
    key="office-data",
    name="Office Data Workbench",
    description="Office-style ribbon matching the Home/Data Manipulation/Insert/Appearance/Export layout.",
    tabs=(
        RibbonTabTemplate("home", "Home", activate=True, groups=(
            RibbonGroupTemplate("selection", "Selection", width=220, layout="small", commands=(
                _cmd("copy", "Copy", size="small"),
                _cmd("paste", "Paste", kind="split", size="small"),
                _cmd("duplicate", "Duplicate", size="small"),
                _cmd("cut", "Cut", size="small"),
                _cmd("delete", "Delete", size="small"),
            )),
            RibbonGroupTemplate("data", "Data", width=220, layout="large", commands=(
                _cmd("new_data_set", "New\nData Set", size="large"),
                _cmd("paste_table", "Paste\nTable", size="large"),
                _cmd("enter_table", "Enter\nTable", size="large"),
            )),
            RibbonGroupTemplate("page_layout", "Page Layout", width=180, layout="small", commands=(
                _cmd("new_page", "New Page", kind="menu", size="small"),
                _cmd("layout", "Layout", kind="menu", size="small"),
                _cmd("reset_layout", "Reset", size="small"),
            )),
            RibbonGroupTemplate("tables", "Tables", width=105, layout="large", commands=(
                _cmd("table", "Table", size="large"),
            )),
            RibbonGroupTemplate("charts", "Charts", width=105, layout="large", commands=(
                _cmd("chart", "Chart", kind="menu", size="large"),
            )),
            RibbonGroupTemplate("zoom", "Zoom", width=190, layout="mixed", commands=(
                _cmd("zoom", "Zoom", size="small"),
                _cmd("fit_window", "Fit to\nWindow", size="large"),
            )),
            RibbonGroupTemplate("more", "More", width=100, layout="large", commands=(
                _cmd("utilities", "Utilities", kind="menu", size="large"),
            )),
            RibbonGroupTemplate("search", "Search", width=110, layout="large", commands=(
                _cmd("find_replace", "Find &\nReplace", size="large"),
            )),
        )),
        RibbonTabTemplate("data_manipulation", "Data Manipulation", groups=(
            RibbonGroupTemplate("rows_columns", "Rows && Columns", width=210, layout="small", commands=(
                _cmd("insert_row", "Insert Row", size="small"),
                _cmd("delete_row", "Delete Row", size="small"),
                _cmd("insert_column", "Insert Column", size="small"),
                _cmd("delete_column", "Delete Column", size="small"),
            )),
            RibbonGroupTemplate("transform", "Transform", width=230, layout="small", commands=(
                _cmd("sort", "Sort", size="small"),
                _cmd("filter", "Filter", size="small"),
                _cmd("formula", "Formula", size="small"),
                _cmd("normalize", "Normalize", size="small"),
            )),
        )),
        RibbonTabTemplate("insert", "Insert", groups=(
            RibbonGroupTemplate("insert_data", "Data", width=180, layout="large", commands=(
                _cmd("insert_table", "Table", size="large"),
                _cmd("insert_chart", "Chart", kind="menu", size="large"),
            )),
            RibbonGroupTemplate("insert_objects", "Objects", width=190, layout="small", commands=(
                _cmd("insert_text", "Text", size="small"),
                _cmd("insert_image", "Image", size="small"),
                _cmd("insert_shape", "Shape", kind="menu", size="small"),
            )),
        )),
        RibbonTabTemplate("appearance", "Appearance", groups=(
            RibbonGroupTemplate("view", "View", width=180, layout="small", commands=(
                _cmd("show_grid", "Grid", size="small", checkable=True, checked=True),
                _cmd("show_guides", "Guides", size="small", checkable=True),
                _cmd("show_status", "Status Bar", size="small", checkable=True, checked=True),
            )),
            RibbonGroupTemplate("format", "Format", width=210, layout="small", commands=(
                _cmd("font", "Font", kind="menu", size="small"),
                _cmd("theme", "Theme", kind="menu", size="small"),
                _cmd("reset_style", "Reset Style", size="small"),
            )),
        )),
        RibbonTabTemplate("export", "Export", groups=(
            RibbonGroupTemplate("export_file", "Export", width=220, layout="large", commands=(
                _cmd("export_image", "Image", kind="menu", size="large"),
                _cmd("export_data", "Data", kind="menu", size="large"),
            )),
            RibbonGroupTemplate("share", "Share", width=150, layout="small", commands=(
                _cmd("copy_link", "Copy Link", size="small"),
                _cmd("open_folder", "Open Folder", size="small"),
            )),
        )),
    ),
)


DOCUMENT_TEMPLATE = RibbonTemplate(
    key="document",
    name="Document Editor",
    description="Compact document editing ribbon.",
    tabs=(
        RibbonTabTemplate("home", "Home", activate=True, groups=(
            RibbonGroupTemplate("clipboard", "Clipboard", width=170, layout="small", commands=(
                _cmd("doc_cut", "Cut", size="small"),
                _cmd("doc_copy", "Copy", size="small"),
                _cmd("doc_paste", "Paste", kind="split", size="small"),
            )),
            RibbonGroupTemplate("editing", "Editing", width=180, layout="small", commands=(
                _cmd("doc_undo", "Undo", size="small"),
                _cmd("doc_redo", "Redo", size="small"),
                _cmd("doc_find", "Find", size="small"),
            )),
        )),
        RibbonTabTemplate("insert", "Insert", groups=(
            RibbonGroupTemplate("objects", "Objects", width=210, layout="large", commands=(
                _cmd("doc_table", "Table", size="large"),
                _cmd("doc_image", "Image", size="large"),
            )),
        )),
        RibbonTabTemplate("view", "View", groups=(
            RibbonGroupTemplate("document_view", "View", width=190, layout="small", commands=(
                _cmd("doc_zoom_in", "Zoom In", size="small"),
                _cmd("doc_zoom_out", "Zoom Out", size="small"),
                _cmd("doc_fit", "Fit Window", size="small"),
            )),
        )),
    ),
    density="compact",
)


DATA_ANALYSIS_TEMPLATE = RibbonTemplate(
    key="data-analysis",
    name="Data Analysis",
    description="Data import, transform, analysis, plotting and export workflow.",
    tabs=(
        RibbonTabTemplate("data", "Data", activate=True, groups=(
            RibbonGroupTemplate("import", "Import", width=220, layout="large", commands=(
                _cmd("data_open", "Open Data", size="large"),
                _cmd("data_import", "Import", kind="menu", size="large"),
            )),
            RibbonGroupTemplate("clean", "Clean", width=210, layout="small", commands=(
                _cmd("data_filter", "Filter", size="small"),
                _cmd("data_sort", "Sort", size="small"),
                _cmd("data_missing", "Missing Values", kind="menu", size="small"),
            )),
        )),
        RibbonTabTemplate("analyze", "Analyze", groups=(
            RibbonGroupTemplate("statistics", "Statistics", width=220, layout="small", commands=(
                _cmd("analysis_summary", "Summary", size="small"),
                _cmd("analysis_regression", "Regression", kind="menu", size="small"),
                _cmd("analysis_compare", "Compare", kind="menu", size="small"),
            )),
        )),
        RibbonTabTemplate("plot", "Plot", groups=(
            RibbonGroupTemplate("charts", "Charts", width=270, layout="large", commands=(
                _cmd("plot_line", "Line", size="large"),
                _cmd("plot_scatter", "Scatter", size="large"),
                _cmd("plot_more", "More", kind="menu", size="large"),
            )),
        )),
        RibbonTabTemplate("export", "Export", groups=(
            RibbonGroupTemplate("results", "Results", width=220, layout="large", commands=(
                _cmd("analysis_export_data", "Data", kind="menu", size="large"),
                _cmd("analysis_export_chart", "Chart", kind="menu", size="large"),
            )),
        )),
    ),
)


PLOT_WORKBENCH_TEMPLATE = RibbonTemplate(
    key="plot-workbench",
    name="Plot Workbench",
    description="Generic plot/digitizer ribbon with axes, series, edit and export tools.",
    tabs=(
        RibbonTabTemplate("home", "Home", activate=True, groups=(
            RibbonGroupTemplate("source", "Source", width=190, layout="large", commands=(
                _cmd("plot_open_image", "Open\nImage", size="large"),
                _cmd("plot_reset", "Reset", size="large"),
            )),
            RibbonGroupTemplate("selection", "Selection", width=190, layout="small", commands=(
                _cmd("plot_pick", "Pick Point", size="small", checkable=True),
                _cmd("plot_edit", "Edit Points", size="small", checkable=True),
                _cmd("plot_delete", "Delete", size="small"),
            )),
        )),
        RibbonTabTemplate("axes", "Axes", groups=(
            RibbonGroupTemplate("calibration", "Calibration", width=240, layout="large", commands=(
                _cmd("axis_x", "X Axis", size="large"),
                _cmd("axis_y", "Y Axis", size="large"),
                _cmd("axis_settings", "Settings", kind="menu", size="large"),
            )),
        )),
        RibbonTabTemplate("series", "Series", groups=(
            RibbonGroupTemplate("series_tools", "Series", width=240, layout="small", commands=(
                _cmd("series_add", "Add Series", size="small"),
                _cmd("series_color", "Sample Color", size="small"),
                _cmd("series_extract", "Extract Points", size="small"),
                _cmd("series_clear", "Clear Series", size="small"),
            )),
        )),
        RibbonTabTemplate("view", "View", groups=(
            RibbonGroupTemplate("zoom", "Zoom", width=190, layout="small", commands=(
                _cmd("plot_zoom_in", "Zoom In", size="small"),
                _cmd("plot_zoom_out", "Zoom Out", size="small"),
                _cmd("plot_fit", "Fit Window", size="small"),
            )),
        )),
        RibbonTabTemplate("export", "Export", groups=(
            RibbonGroupTemplate("output", "Output", width=220, layout="large", commands=(
                _cmd("plot_export_csv", "CSV", size="large"),
                _cmd("plot_export_image", "Image", kind="menu", size="large"),
            )),
        )),
    ),
    density="compact",
)


for _template in (
    OFFICE_DATA_TEMPLATE,
    DOCUMENT_TEMPLATE,
    DATA_ANALYSIS_TEMPLATE,
    PLOT_WORKBENCH_TEMPLATE,
):
    register_ribbon_template(_template)


__all__ = [
    "RibbonCommandTemplate",
    "RibbonGroupTemplate",
    "RibbonTabTemplate",
    "RibbonTemplate",
    "RibbonTemplateInstance",
    "RibbonTemplateFactory",
    "register_ribbon_template",
    "get_ribbon_template",
    "ribbon_template_names",
    "apply_ribbon_template",
    "create_ribbon_from_template",
    "OFFICE_DATA_TEMPLATE",
    "DOCUMENT_TEMPLATE",
    "DATA_ANALYSIS_TEMPLATE",
    "PLOT_WORKBENCH_TEMPLATE",
]
