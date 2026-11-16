"""Application-wide typography choices shared by WinUx and DearUIQt hosts."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

DEFAULT_UI_FONT_FAMILY = "Arial"
DEFAULT_UI_FONT_SIZE = 15
DEFAULT_UI_FONT_STYLE = "Regular"
DEFAULT_UI_THEME = "Light"
AVAILABLE_UI_THEMES = ("Light", "Dark")
MIN_UI_FONT_SIZE = 10
MAX_UI_FONT_SIZE = 24

# Known Windows families provide deterministic regular/bold fallbacks. The
# registry scanner below augments this catalog with other installed fonts.
_FONT_CATALOG = {
    "Segoe UI": (("segoeui.ttf",), ("seguisb.ttf", "segoeuib.ttf")),
    "Arial": (("arial.ttf",), ("arialbd.ttf",)),
    "Calibri": (("calibri.ttf",), ("calibrib.ttf",)),
    "Aptos": (("aptos.ttf",), ("aptos-bold.ttf", "aptosdisplay-bold.ttf")),
    "Tahoma": (("tahoma.ttf",), ("tahomabd.ttf",)),
    "Verdana": (("verdana.ttf",), ("verdanab.ttf",)),
    "Trebuchet MS": (("trebuc.ttf",), ("trebucbd.ttf",)),
    "Georgia": (("georgia.ttf",), ("georgiab.ttf",)),
    "Times New Roman": (("times.ttf",), ("timesbd.ttf",)),
}
_STYLE_SUFFIX = re.compile(
    r"\s+(Regular|Book|Roman|Normal|Medium|Light|Thin|Black|Heavy|Semibold|Semi Bold|"
    r"Demi|Bold|Italic|Oblique|Bold Italic|BoldItalic)$", re.IGNORECASE)
_NON_REGULAR = re.compile(
    r"\b(Bold|Italic|Oblique|Semibold|Semi Bold|Demi|Black|Heavy|Light|Thin)\b",
    re.IGNORECASE)



def normalize_ui_theme(value):
    text = str(value or "").strip().casefold()
    return "Dark" if text == "dark" else DEFAULT_UI_THEME

def windows_fonts_dir():
    return Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"


def _font_path(value):
    path = Path(str(value or ""))
    if not path.is_absolute():
        path = windows_fonts_dir() / path
    return path if path.is_file() else None


def _first_existing(names):
    for name in names:
        path = _font_path(name)
        if path is not None:
            return path
    return None


def _registry_family(display_name):
    name = re.sub(r"\s*\((TrueType|OpenType)\)\s*$", "", str(display_name), flags=re.I).strip()
    name = _STYLE_SUFFIX.sub("", name).strip()
    return name


@lru_cache(maxsize=1)
def _registry_fonts():
    """Return installed font registry rows as ``(display, family, path)``."""
    if os.name != "nt":
        return ()
    try:
        import winreg
    except Exception:
        return ()
    rows = []
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    )
    for hive, key_name in locations:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                index = 0
                while True:
                    try:
                        display, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    path = _font_path(value)
                    if path is None or path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
                        continue
                    family = _registry_family(display)
                    if family:
                        rows.append((str(display), family, path))
        except OSError:
            continue
    return tuple(rows)


@lru_cache(maxsize=1)
def _available_ui_font_families():
    """Return installed UI-capable font families with the default first."""
    families = set()
    for family, (regular, _bold) in _FONT_CATALOG.items():
        if _first_existing(regular) is not None:
            families.add(family)
    for display, family, _path in _registry_fonts():
        # Prefer families with a regular/normal face. Styled-only registry rows
        # are still usable when another regular row for the family is present.
        if not _NON_REGULAR.search(display):
            families.add(family)
    ordered = sorted(families, key=str.casefold)
    if DEFAULT_UI_FONT_FAMILY in ordered:
        ordered.remove(DEFAULT_UI_FONT_FAMILY)
    ordered.insert(0, DEFAULT_UI_FONT_FAMILY)
    return tuple(ordered)


def _style_from_display(display, family=""):
    """Return a user-facing style name for one Windows font registry row."""
    value = re.sub(r"\s*\((TrueType|OpenType)\)\s*$", "", str(display or ""), flags=re.I).strip()
    family = str(family or "").strip()
    if family and value.lower().startswith(family.lower()):
        value = value[len(family):].strip(" -")
    value = value or DEFAULT_UI_FONT_STYLE
    aliases = {
        "normal": "Regular", "roman": "Regular", "book": "Regular",
        "bolditalic": "Bold Italic", "bold italic": "Bold Italic",
        "semi bold": "Semibold", "demi": "Semibold",
    }
    return aliases.get(value.casefold(), value)


@lru_cache(maxsize=256)
def _available_ui_font_styles(family):
    family = normalize_ui_font_family(family)
    styles = []
    for display, fam, _path in _registry_fonts():
        if fam != family:
            continue
        style = _style_from_display(display, fam)
        if style not in styles:
            styles.append(style)
    if family in _FONT_CATALOG:
        regular, bold = _FONT_CATALOG[family]
        if _first_existing(regular) is not None and "Regular" not in styles:
            styles.insert(0, "Regular")
        if _first_existing(bold) is not None and "Bold" not in styles:
            styles.append("Bold")
    if styles:
        # Keep the native faces discovered from Windows, but expose the standard
        # Windows quartet so the selector does not collapse to a single entry
        # whenever the registry reports only one face for a family.
        for synthetic in ("Regular", "Bold", "Italic", "Bold Italic"):
            if synthetic not in styles:
                styles.append(synthetic)
    if not styles:
        styles = [DEFAULT_UI_FONT_STYLE]
    order = {"Regular": 0, "Italic": 1, "Bold": 2, "Bold Italic": 3,
             "Light": 4, "Semilight": 5, "Semibold": 6, "Black": 7}
    return tuple(sorted(styles, key=lambda x: (order.get(x, 50), x.casefold())))


def available_ui_font_styles(family):
    return list(_available_ui_font_styles(str(family or "")))


def normalize_ui_font_style(family, style):
    styles = available_ui_font_styles(family)
    requested = str(style or "").strip()
    aliases = {
        "normal": "Regular",
        "roman": "Regular",
        "book": "Regular",
        "oblique": "Italic",
        "bolditalic": "Bold Italic",
        "bold italic": "Bold Italic",
    }
    requested = aliases.get(requested.casefold(), requested)
    for candidate in styles:
        if candidate.casefold() == requested.casefold():
            return candidate
    return DEFAULT_UI_FONT_STYLE if DEFAULT_UI_FONT_STYLE in styles else styles[0]


def resolve_ui_font_face_path(family=None, style=None):
    """Resolve one exact installed face for preview/body rendering."""
    normalized = normalize_ui_font_family(family)
    selected_style = normalize_ui_font_style(normalized, style)
    rows = [(display, path) for display, fam, path in _registry_fonts() if fam == normalized]
    for display, path in rows:
        if _style_from_display(display, normalized).casefold() == selected_style.casefold():
            return normalized, selected_style, path

    style_cf = selected_style.casefold()
    def _match(display):
        value = str(display or "")
        has_bold = bool(re.search(r"\b(Semibold|Semi Bold|Demi|Bold|Black|Heavy)\b", value, re.I))
        has_italic = bool(re.search(r"\b(Italic|Oblique)\b", value, re.I))
        if style_cf == "bold italic":
            return has_bold and has_italic
        if style_cf == "italic":
            return has_italic and not has_bold
        if style_cf in {"bold", "semibold", "black", "heavy"}:
            return has_bold and not has_italic
        return not has_bold and not has_italic

    fallback = next((path for display, path in rows if _match(display)), None)
    if fallback is not None:
        return normalized, selected_style, fallback
    if normalized in _FONT_CATALOG:
        regular_names, bold_names = _FONT_CATALOG[normalized]
        if style_cf in {"bold", "semibold", "black", "heavy", "bold italic"}:
            path = _first_existing(bold_names) or _first_existing(regular_names)
        else:
            path = _first_existing(regular_names) or _first_existing(bold_names)
        if path is not None:
            return normalized, selected_style, path
    if rows:
        return normalized, selected_style, rows[0][1]
    if normalized != DEFAULT_UI_FONT_FAMILY:
        return resolve_ui_font_face_path(DEFAULT_UI_FONT_FAMILY, DEFAULT_UI_FONT_STYLE)
    return normalized, selected_style, None


def available_ui_font_families():
    return list(_available_ui_font_families())


def normalize_ui_font_family(value):
    family = str(value or "").strip()
    if family and family in available_ui_font_families():
        return family
    return DEFAULT_UI_FONT_FAMILY


def normalize_ui_font_size(value):
    try:
        size = int(round(float(value)))
    except (TypeError, ValueError):
        size = DEFAULT_UI_FONT_SIZE
    return max(MIN_UI_FONT_SIZE, min(MAX_UI_FONT_SIZE, size))


def resolve_ui_font_paths(family=None, style=None):
    """Return ``(normalized_family, regular_path, heading_path)``.

    Saved fonts that no longer exist automatically fall back to Segoe UI.
    """
    normalized = normalize_ui_font_family(family)
    selected_style = normalize_ui_font_style(normalized, style)
    face_family, _face_style, selected_face = resolve_ui_font_face_path(normalized, selected_style)
    if normalized in _FONT_CATALOG:
        regular_names, bold_names = _FONT_CATALOG[normalized]
        regular = selected_face or _first_existing(regular_names)
        heading = _first_existing(bold_names) or regular
        if regular is not None:
            return normalized, regular, heading

    rows = [(display, path) for display, fam, path in _registry_fonts() if fam == normalized]
    regular = selected_face or next((path for display, path in rows if not _NON_REGULAR.search(display)), None)
    heading = next((path for display, path in rows if re.search(r"\b(Semibold|Semi Bold|Bold|Demi)\b", display, re.I)), None)
    if regular is not None:
        return normalized, regular, heading or regular

    if normalized != DEFAULT_UI_FONT_FAMILY:
        return resolve_ui_font_paths(DEFAULT_UI_FONT_FAMILY, DEFAULT_UI_FONT_STYLE)
    return normalized, None, None


__all__ = [
    "DEFAULT_UI_FONT_FAMILY", "DEFAULT_UI_FONT_SIZE", "DEFAULT_UI_FONT_STYLE",
    "DEFAULT_UI_THEME", "AVAILABLE_UI_THEMES", "normalize_ui_theme",
    "MIN_UI_FONT_SIZE", "MAX_UI_FONT_SIZE",
    "available_ui_font_families", "available_ui_font_styles",
    "normalize_ui_font_family", "normalize_ui_font_style",
    "normalize_ui_font_size", "resolve_ui_font_face_path", "resolve_ui_font_paths",
]
