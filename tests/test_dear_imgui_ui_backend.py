from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "WinUx"

# Server Notepad is the one explicitly tracked legacy migration island. No new
# Tk import is allowed anywhere else in the WinUx UI/runtime package.
LEGACY_NOTEPAD_TK = {
    "components/server_notepad_tabs.py",
    "dialogs/modern.py",
    "services/server_notepad_layout.py",
    "services/server_notepad_editor.py",
    "services/server_notepad_process.py",
    "services/server_notepad_search.py",
    # Shared Win32/resource helpers still expose legacy Tk-only functions used
    # exclusively by the Server Notepad migration island. The main WinUx/DPG
    # dialog path does not call those functions.
    "platform/native_dialog_host.py",
    "resources.py",
}


def _tk_imports():
    found = set()
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if "import tkinter" in text or "from tkinter" in text:
            found.add(rel)
    return found


def test_tk_ui_is_caged_to_server_notepad_migration_island():
    assert _tk_imports() <= LEGACY_NOTEPAD_TK


def test_login_and_folder_chooser_use_no_secondary_ui_toolkit():
    for rel in (
        "dialogs/login_form.py",
        "dialogs/local_folder_form.py",
        "components/qt_combo_box.py",
        "services/floating_dialog_process.py",
    ):
        source = (ROOT / rel).read_text(encoding="utf-8")
        assert "tkinter" not in source
        assert "PyQt" not in source
        assert "PySide" not in source


def test_backend_explicit_imgui_item_view_aliases_exist():
    source = (ROOT / "widgets/item_views.py").read_text(encoding="utf-8")
    assert "ImGuiDataGridView = QtDataGridView" in source
    assert "ImGuiListView = QtListView" in source
    combo = (ROOT / "components/qt_combo_box.py").read_text(encoding="utf-8")
    assert "class ImGuiComboBox:" in combo
    assert "QtComboBox = ImGuiComboBox" in combo
