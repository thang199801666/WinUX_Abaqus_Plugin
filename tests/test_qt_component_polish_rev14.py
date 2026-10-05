"""Static contracts for WinUx 1.1.0 Qt component polish revision 14."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_multiline_views_use_shared_qplaintextedit_contract():
    theme = read("dialogs/theme.py")
    dialog = read("dialogs/qt_dialog.py")
    diagnostics = read("dialogs/diagnostics_form.py")
    assert "def plain_text_edit_theme():" in theme
    assert "def plain_text_edit(self, value=" in dialog
    assert "self.plain_text_edit(" in diagnostics
    assert 'self.line_edit("", multiline=True' not in diagnostics


def test_bookmarks_and_sync_use_explicit_qheader_column_contracts():
    bookmarks = read("dialogs/bookmarks_form.py")
    sync = read("dialogs/sync_preview_form.py")
    assert '"key": "location", "label": "Location", "width": 86' in bookmarks
    assert '"key": "path", "label": "Path", "stretch": 2.4' in bookmarks
    assert '"key": "status", "label": "Status", "width": 112' in sync
    assert '"key": "action", "label": "Recommended action", "width": 156' in sync
    assert "status_item=self.status" in bookmarks
    assert "status_item=self.status" in sync


def test_progress_dialog_uses_qdialogbuttonbox_status_slot():
    src = read("dialogs/progress_form.py")
    assert "self.preferred_size = (500, 192)" in src
    assert "status_item=self.stats" in src
    assert "dpg.add_spacer(parent=self.content, height=2)" in src


def test_ssh_console_context_menu_uses_shared_qmenu_renderer():
    src = read("dialogs/console_form.py")
    assert "from ..widgets import QMenu" in src
    assert "def _create_context_menu(self):" in src
    assert "menu.setActionEnabled(\"copy\"" in src
    assert "menu.popup((mx, my), context=self)" in src
    assert "popup=True" not in src
    assert "dpg.add_selectable(" not in src


def test_product_version_remains_fixed_at_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
