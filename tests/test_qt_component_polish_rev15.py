"""Static contracts for WinUx 1.1.0 Qt component polish revision 15."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_dock_title_menu_uses_shared_qmenu_contract():
    src = read("components/dock_widget.py")
    assert "from ..widgets import QMenu" in src
    assert "self._title_menu_obj = QMenu(" in src
    assert "self._title_menu_obj.triggered.connect(self._title_menu_triggered)" in src
    block = src.split("# Qt exposes dock actions from the title area.", 1)[1].split("self.title_overlay", 1)[0]
    assert "dpg.add_window(" not in block
    assert "dpg.add_selectable(" not in block
    assert '"checkable": True' in src


def test_resource_menu_bar_uses_shared_qmenu_with_icon_gutter():
    src = read("components/toolbar.py")
    assert "from ..widgets import QMenu" in src
    block = src.split("class ResourceMenuBar:", 1)[1].split("def add_resource_button", 1)[0]
    assert "popup = QMenu(actions" in block
    assert '"icon": texture' in block
    assert "register_pointer_protected_item(popup.tag)" in block
    assert "dpg.add_window(" not in block
    assert "dpg.add_selectable(" not in block


def test_blocking_dialog_uses_qmessagebox_like_vector_body():
    dialog = read("dialogs/qt_dialog.py")
    form = read("dialogs/blocking_form.py")
    assert "def message_box_body(" in dialog
    body = dialog.split("def message_box_body", 1)[1].split("def field", 1)[0]
    assert "dpg.add_drawlist(" in body
    assert "dpg.draw_triangle(" in body
    assert "dpg.draw_circle(" in body
    assert "dpg.draw_line(" in body
    assert "self.message_box_body(" in form
    assert "self.header(headings.get(title, title))" not in form


def test_progress_bar_supports_semantic_qt_states():
    style = read("widgets/imgui_qt_style.py")
    controls = read("widgets/controls.py")
    progress = read("dialogs/progress_form.py")
    assert 'def progress_theme(backend, *, state="normal")' in style
    assert '"error": p.DANGER' in style
    assert '"paused": (205, 132, 0, 255)' in style
    assert "def setState(self, state=\"normal\")" in controls
    assert 'self._current_progress.setState("error")' in progress
    assert 'self._overall_progress.setState("paused")' in progress
    assert "error_text_theme()" in progress


def test_product_version_remains_fixed_at_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
