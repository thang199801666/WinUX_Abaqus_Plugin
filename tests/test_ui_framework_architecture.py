from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "DearUIQt"
UI = ROOT / "WinUx" / "ui"
COMPONENTS = UI / "components"
BEHAVIORS = UI / "behaviors"


def test_dearuiqt_is_root_level_standalone_package():
    assert LIB.is_dir()
    assert not (UI / "framework").exists()
    for legacy in ("shared_ui", "ui_framework", "widgets", "components"):
        assert not (ROOT / "WinUx" / legacy).exists()


def test_dearuiqt_is_grouped_by_concern():
    assert (LIB / "qt" / "core.py").is_file()
    assert (LIB / "qt" / "widget.py").is_file()
    assert (LIB / "qt" / "layouts.py").is_file()
    assert (LIB / "qt" / "scroller.py").is_file()
    assert (LIB / "qt" / "scroll_area.py").is_file()
    assert (LIB / "qt" / "splitter.py").is_file()
    assert (LIB / "qt" / "tool_bar.py").is_file()
    assert (LIB / "ribbon" / "bar.py").is_file()
    assert (LIB / "splitter" / "controller.py").is_file()
    assert (LIB / "docking" / "dock_widget.py").is_file()
    assert (LIB / "widgets" / "color_field.py").is_file()
    assert (UI / "hosting" / "host.py").is_file()
    assert (UI / "native" / "native_dialog_host.py").is_file()
    assert (COMPONENTS / "explorer_list_view.py").is_file()
    assert (BEHAVIORS / "splitter_behavior.py").is_file()


def test_dearuiqt_has_no_winux_import_dependency():
    source = "\n".join(path.read_text(encoding="utf-8") for path in LIB.rglob("*.py"))
    lower = source.lower()
    for token in ("import winux", "from winux", "winux.import_module"):
        assert token not in lower, f"DearUIQt must not depend on WinUx ({token})"
    # Keep the guard import-statement based: DearUIQt source is application
    # independent even though historical comments may reference the WinUx host.
    assert "import WinUx" not in source
    assert "from WinUx" not in source
    assert "importlib.import_module(WinUx" not in source


def test_application_components_depend_on_dearuiqt_not_legacy_facades():
    source = "\n".join(path.read_text(encoding="utf-8") for path in COMPONENTS.rglob("*.py"))
    assert "DearUIQt" in source
    assert "ui.framework" not in source
    assert "shared_ui" not in source
    assert "ui_framework" not in source


def test_splitter_core_and_host_behavior_are_separated():
    model = (LIB / "splitter" / "model.py").read_text(encoding="utf-8")
    controller = (LIB / "splitter" / "controller.py").read_text(encoding="utf-8")
    behavior = (BEHAVIORS / "splitter_behavior.py").read_text(encoding="utf-8")
    adapter = (BEHAVIORS / "splitter_layout.py").read_text(encoding="utf-8")
    assert "dearpygui" not in model
    assert "dearpygui" not in controller
    assert "SplitterController" in controller
    assert "def _apply_split_layout" in behavior
    assert "def _splitter_modal_window_visible" in behavior
    assert "_visible_modal_window_exists" in adapter


def test_winux_specific_generic_shims_were_removed():
    assert not (UI / "color_field.py").exists()
    assert not (UI / "runtime.py").exists()
    assert not (UI / "window.py").exists()
    assert not (COMPONENTS / "imgui_combo_box.py").exists()
