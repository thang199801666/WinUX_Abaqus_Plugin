"""Portability guards for the standalone DearUIQt package."""
from pathlib import Path
import subprocess
import sys

from DearUIQt import RibbonResources, SplitterState, split_extent

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT / "DearUIQt"


def test_ribbon_resources_support_explicit_override_without_host_imports():
    base_loader = lambda name, size: (name, size)
    override_loader = lambda name, size: (size, name)
    resolver = lambda name: Path("icons") / name
    resources = RibbonResources(texture_loader=base_loader, icon_path_resolver=resolver)
    merged = resources.merged(texture_loader=override_loader)
    assert merged.texture_loader is override_loader
    assert merged.icon_path_resolver is resolver
    assert resources.texture_loader is base_loader


def test_generic_splitter_enforces_minimums_when_they_fit():
    sizes = split_extent(1000, 0.5, separator_size=6, min_first=300, min_second=400)
    assert sizes.first == 497
    assert sizes.second == 497
    assert sizes.total == 1000


def test_generic_splitter_uses_fractional_bounds_when_container_is_tight():
    sizes = split_extent(200, 0.05, separator_size=4, min_first=180, min_second=180)
    assert sizes.first == round(196 * 0.30)
    assert sizes.second == 196 - sizes.first


def test_splitter_state_can_be_driven_by_pointer_position():
    state = SplitterState(0.25)
    state.drag_to(600, 1200, separator_size=4)
    assert 0.50 <= state.ratio <= 0.51
    first, second = state.sizes(1200, separator_size=4, min_first=100, min_second=100).as_tuple()
    assert first + second + 4 == 1200


def test_package_root_remains_backend_light_in_clean_interpreter():
    code = (
        "import sys; import DearUIQt as f; "
        "assert 'dearpygui.dearpygui' not in sys.modules; "
        "assert f.SplitterState(0.5).ratio == 0.5"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_ribbon_type_can_be_imported_without_loading_native_backend():
    code = (
        "import sys; from DearUIQt.ribbon import RibbonBar; "
        "assert RibbonBar.__name__ == 'RibbonBar'; "
        "assert 'dearpygui.dearpygui' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_package_uses_relative_internal_imports_and_no_winux_dependency():
    for path in FRAMEWORK.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from WinUx" not in source
        assert "import WinUx" not in source


def test_splitter_controller_preserves_pointer_offset_during_drag():
    from DearUIQt import SplitterController, SplitterPolicy, SplitterState
    controller = SplitterController(
        state=SplitterState(0.5),
        policy=SplitterPolicy(separator_size=10, min_first=100, min_second=100),
    )
    divider = controller.divider_position(1000)
    controller.begin_drag(divider + 7, 1000)
    controller.update_drag(divider + 107, 1000)
    assert 0.59 <= controller.ratio <= 0.61
    assert controller.end_drag() is True
    assert controller.end_drag() is False


def test_winux_splitter_host_behavior_is_outside_dearuiqt():
    behavior = ROOT / "WinUx" / "ui" / "behaviors" / "splitter_behavior.py"
    adapter = ROOT / "WinUx" / "ui" / "behaviors" / "splitter_layout.py"
    assert behavior.is_file()
    assert adapter.is_file()
    assert "def _apply_split_layout" in behavior.read_text(encoding="utf-8")
    assert "class SplitterLayoutMixin(SplitterLayoutBehaviorMixin)" in adapter.read_text(encoding="utf-8")
    assert "SplitterLayoutMixin" not in (FRAMEWORK / "splitter" / "__init__.py").read_text(encoding="utf-8")


def test_standalone_export_is_importable(tmp_path):
    output = tmp_path / "portable-ui"
    result = subprocess.run([
        sys.executable, str(ROOT / "tools" / "export_ui_framework.py"), str(output),
        "--import-package", "portable_ui",
    ], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    package = output / "portable_ui"
    assert (package / "qt" / "core.py").is_file()
    assert (package / "docking" / "dock_widget.py").is_file()
    code = (
        "import sys; sys.path.insert(0, r'%s'); "
        "import portable_ui as ui; "
        "assert ui.SplitterController().ratio == 0.5; assert ui.QSplitter.__name__ == 'QSplitter'; assert ui.QToolBar.__name__ == 'QToolBar'; "
        "assert 'dearpygui.dearpygui' not in sys.modules; "
        "from portable_ui.qt.item_models import QtItemViewState; "
        "from portable_ui.ribbon import RibbonBar; "
        "assert QtItemViewState(True).replace(['a']).keys == ['a']; "
        "assert RibbonBar.__name__ == 'RibbonBar'"
    ) % str(output)
    imported = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert imported.returncode == 0, imported.stderr
