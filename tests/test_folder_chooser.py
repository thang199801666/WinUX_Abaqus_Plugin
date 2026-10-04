from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "WinUx" / "view.py"
FORM = ROOT / "WinUx" / "dialogs" / "local_folder_form.py"
ADAPTER = ROOT / "WinUx" / "dialogs" / "floating_adapters.py"
FORMS = ROOT / "WinUx" / "dialogs" / "floating_forms.py"
SERVICES = ROOT / "WinUx" / "services"


def test_local_folder_chooser_is_dear_imgui_only():
    view = VIEW.read_text(encoding="utf-8")
    form = FORM.read_text(encoding="utf-8")
    assert "FolderChooser" not in view
    assert "LocalFolderDialog" in view
    assert "dearpygui.dearpygui" in form
    assert "tkinter" not in form
    assert "filedialog" not in form
    assert not (SERVICES / "folder_chooser_process.py").exists()


def test_local_folder_form_uses_shared_item_view_and_async_directory_listing():
    source = FORM.read_text(encoding="utf-8")
    assert "QtListView" in source
    assert "os.scandir" in source
    assert "threading.Thread" in source
    assert "self.view.after(0, self._apply_entries" in source
    assert "Select Folder" in source


def test_local_folder_uses_floating_dialog_result_protocol():
    adapters = ADAPTER.read_text(encoding="utf-8")
    forms = FORMS.read_text(encoding="utf-8")
    assert "class LocalFolderDialog(ResultDialog):" in adapters
    assert 'view, "local_folder", "Open Folder"' in adapters
    assert 'elif kind == "local_folder":' in forms
    assert "on_result=result" in forms
