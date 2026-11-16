"""Regression coverage for the reusable DearUIQt font selector."""
from __future__ import annotations

from pathlib import Path

from DearUIQt.dialogs import QFontDialog, QFontSelection


def test_font_selector_is_public_dearuiqt_surface():
    assert QFontDialog is not None
    assert QFontSelection("Arial", "Bold", 14).size == 14


def test_font_selector_layout_is_metric_driven():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/font_dialog.py").read_text(encoding="utf-8")
    assert "QFontMetrics" in source
    assert "horizontalAdvance" in source
    assert "lineSpacing" in source
    assert "family_text_width" in source
    assert "QFontDatabase" in source


def test_settings_opens_reusable_font_dialog():
    root = Path(__file__).resolve().parents[1]
    source = (root / "WinUx/dialogs/settings/settings_form.py").read_text(encoding="utf-8")
    assert "QFontDialog(" in source
    assert "styles_provider=available_ui_font_styles" in source
    assert "face_resolver=resolve_ui_font_face_path" in source
    assert "on_selected=self._font_selector_selected" in source


def test_font_selector_matches_windows_like_lower_region_and_navigation():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/font_dialog.py").read_text(encoding="utf-8")
    assert "self._lower" in source
    assert "QHBoxLayout" in source
    assert "QVBoxLayout" in source
    assert "from ..layouts import QGridLayout" not in source
    assert "self.form_layout(" not in source
    assert "self.button_box(" not in source
    assert "add_table" not in source
    assert "lower_right_width" in source
    assert "visible_rows=13" in source
    assert "startswith(query)" in source
    assert "itemDoubleClicked.connect" in source


def test_settings_defers_font_dialog_until_pointer_release_finishes():
    root = Path(__file__).resolve().parents[1]
    source = (root / "WinUx/dialogs/settings/settings_form.py").read_text(encoding="utf-8")
    start = source.index("    def _open_font_selector(self):")
    end = source.index("    def _font_selector_selected", start)
    method = source[start:end]
    assert "_font_selector_open_pending" in method
    assert "self.view.after(0, create_font_selector)" in method
    assert method.index("self.view.after(0, create_font_selector)") > method.index("def create_font_selector")
    assert "QFontDialog(" in method
    assert "if not self.winfo_exists()" in method


def test_font_selector_uses_real_style_combobox_and_native_family_row_fonts():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/font_dialog.py").read_text(encoding="utf-8")
    assert "QComboBox" in source
    assert "self.style_combo" in source
    assert "_set_style_options" in source
    assert "_bind_current_family_row_font" in source
    assert "binder(native, font.nativeId())" in source
    assert "style_list" not in source
    assert "setItemWidget(item, label)" not in source


def test_font_style_catalog_keeps_standard_windows_style_quartet():
    root = Path(__file__).resolve().parents[1]
    source = (root / "WinUx/preferences/appearance.py").read_text(encoding="utf-8")
    assert 'for synthetic in ("Regular", "Bold", "Italic", "Bold Italic")' in source
    assert "resolve_ui_font_face_path" in source


def test_font_style_combo_initializes_with_items_and_forces_preview_sync():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/font_dialog.py").read_text(encoding="utf-8")
    assert "initial_styles = self._normalized_style_options(initial_family)" in source
    assert "initial_styles, current=initial_style" in source
    assert "def _force_combo_preview" in source
    assert "field.setText(text)" in source
    assert "self.style_combo.clear()" in source
    assert "self.style_combo.addItems(styles)" in source


def test_font_selector_current_selection_is_safe_during_partial_construction():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/font_dialog.py").read_text(encoding="utf-8")
    assert 'getattr(self, "script_combo", None)' in source
    start = source.index("    def _bind_current_family_row_font")
    end = source.index("    def _normalized_style_options", start)
    block = source[start:end]
    assert "currentSelection()" not in block
    assert "self._size_editor.text()" in block


def test_font_selector_does_not_bulk_load_installed_font_catalog():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/font_dialog.py").read_text(encoding="utf-8")
    assert "_bind_family_row_fonts(family_items)" not in source
    assert "_bind_current_family_row_font" in source
    assert 'candidate.suffix.lower() not in {".ttf", ".otf"}' in source


def test_font_selector_preview_and_size_editing_are_polished():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/font_dialog.py").read_text(encoding="utf-8")
    assert "self._preview_label.setAlignment(Qt.AlignCenter)" in source
    assert "self._preview_label.setMinimumHeight" in source
    assert "self._size_editor.textEdited.connect(self._size_text_edited" in source
    assert "def _size_text_edited" in source
    assert "width=max(metrics.horizontalAdvance(\"Western\") + pad * 7, lower_right_width)" in source


def test_font_selector_type_to_select_uses_highlighted_family_without_overwriting_prefix():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/font_dialog.py").read_text(encoding="utf-8")
    assert "def _effective_family" in source
    assert "def _sync_family_candidate" in source
    assert "update_editor=False" in source
    assert "self._sync_family_candidate(self.family_list.item(row), update_editor=False)" in source
    assert "family = self._effective_family()" in source
    assert "update_editor=True" in source


def test_font_dialog_footer_is_right_anchored_and_script_not_clipped():
    root = Path(__file__).resolve().parents[1]
    source = (root / "DearUIQt/dialogs/font_dialog.py").read_text(encoding="utf-8")
    assert "dialog_height = max(int(round(line * 42.0)), 620)" in source
    assert "self._footer_layout.addStretch(1)" in source
    assert "max(line * 7, 96)" in source
