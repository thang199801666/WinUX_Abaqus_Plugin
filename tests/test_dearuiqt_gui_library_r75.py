from pathlib import Path
from unittest.mock import MagicMock
import importlib
import sys

ROOT = Path(__file__).resolve().parents[1]


def fake_backend():
    ui = MagicMock()
    ids = iter(range(1000, 10000))
    values, configs = {}, {}

    def create(*args, **kwargs):
        tag = next(ids)
        values[tag] = kwargs.get("default_value", "")
        configs[tag] = dict(kwargs)
        configs[tag].setdefault("enabled", True)
        configs[tag].setdefault("show", kwargs.get("show", True))
        return tag

    for name in (
        "add_input_text", "add_slider_int", "add_vslider_int", "add_spacer",
        "add_separator", "add_child_window", "add_item_handler_registry",
        "add_button", "add_image_button", "add_text",
    ):
        getattr(ui, name).side_effect = create
    ui.get_value.side_effect = lambda tag: values.get(tag, "")
    ui.set_value.side_effect = lambda tag, value: values.__setitem__(tag, value)
    ui.configure_item.side_effect = lambda tag, **kw: configs.setdefault(tag, {}).update(kw)
    ui.get_item_configuration.side_effect = lambda tag: configs.get(tag, {"show": True, "enabled": True})
    ui.get_item_state.return_value = {}
    ui.does_item_exist.return_value = True
    ui.get_item_parent.return_value = 1
    return ui


def test_r75_canonical_packages_own_implementation_not_qt_facades():
    import DearUIQt
    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 14, 0)
    from DearUIQt.core import QObject
    from DearUIQt.widgets import QApplication
    from DearUIQt.gui import QAction
    from DearUIQt.widgets import QPushButton, QSlider, QTextEdit, QScrollBar
    from DearUIQt.layouts import QHBoxLayout, QSplitter
    from DearUIQt.modelview import QListView, QTableView

    assert QObject.__module__.startswith("DearUIQt.core.")
    assert QApplication.__module__.startswith("DearUIQt.core.")
    assert QAction.__module__.startswith("DearUIQt.gui.")
    assert QPushButton.__module__.startswith("DearUIQt.widgets.")
    assert QSlider.__module__.startswith("DearUIQt.widgets.")
    assert QTextEdit.__module__ == "DearUIQt.widgets.text_edit"
    assert QScrollBar.__module__ == "DearUIQt.widgets.scrollbar"
    assert QHBoxLayout.__module__.startswith("DearUIQt.layouts.")
    assert QSplitter.__module__.startswith("DearUIQt.layouts.")
    assert QListView.__module__.startswith("DearUIQt.modelview.")
    assert QTableView.__module__.startswith("DearUIQt.modelview.")


def test_legacy_qt_modules_alias_canonical_module_objects():
    pairs = (
        ("DearUIQt.qt.core", "DearUIQt.core.object"),
        ("DearUIQt.qt.buttons", "DearUIQt.widgets.buttons"),
        ("DearUIQt.qt.layouts", "DearUIQt.layouts.box"),
        ("DearUIQt.qt.item_list", "DearUIQt.modelview.list"),
        ("DearUIQt.qt.palette", "DearUIQt.gui.palette"),
        ("DearUIQt.qt.scroller", "DearUIQt.backends.dearpygui_scroller"),
    )
    for old_name, new_name in pairs:
        assert importlib.import_module(old_name) is importlib.import_module(new_name)


def test_public_catalog_resolution_remains_backend_lazy():
    for name in list(sys.modules):
        if name.startswith("dearpygui"):
            sys.modules.pop(name, None)
    import DearUIQt
    for name in DearUIQt.__all__:
        # Backend-specific escape-hatch exports are allowed to be lazy proxies;
        # resolving common Qt API must not import the native renderer.
        if name in {"DpgScrollerArrowOverlay", "SharedScrollerMetrics", "SharedScrollerPalette"}:
            continue
        getattr(DearUIQt, name)
    assert "dearpygui.dearpygui" not in sys.modules


def test_new_text_scrollbar_and_primitives_work_on_injected_backend():
    from DearUIQt import Qt
    from DearUIQt.widgets import QTextEdit, QScrollBar, QSeparator, QSpacer
    from DearUIQt.layouts import QSpacerItem
    ui = fake_backend()

    text = QTextEdit("alpha", backend=ui)
    text.append("beta")
    assert text.toPlainText() == "alpha\nbeta"
    text.setHtml("<b>hello</b>")
    assert text.toHtml() == "<b>hello</b>"

    scroll = QScrollBar(Qt.Horizontal, backend=ui, minimum=0, maximum=10, value=3)
    scroll.setValue(7)
    assert scroll.value() == 7

    separator = QSeparator(Qt.Horizontal, backend=ui)
    spacer = QSpacer(8, 14, backend=ui)
    item = QSpacerItem(4, 5, backend=ui)
    assert separator.orientation() == Qt.Horizontal
    assert spacer.sizeHint().width() == 8
    item.changeSize(9, 11)
    assert item.sizeHint().height() == 11


def test_canonical_implementation_does_not_import_legacy_qt_namespace():
    canonical_roots = [
        ROOT / "DearUIQt" / "core",
        ROOT / "DearUIQt" / "gui",
        ROOT / "DearUIQt" / "widgets",
        ROOT / "DearUIQt" / "layouts",
        ROOT / "DearUIQt" / "modelview",
    ]
    for folder in canonical_roots:
        for path in folder.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith(("#", "\"\"\"")))
            assert "from ..qt" not in code, path
            assert "from .qt" not in code, path


def test_dearuiqt_is_application_independent_and_winux_uses_public_namespaces():
    for path in (ROOT / "DearUIQt").rglob("*.py"):
        assert "import WinUx" not in path.read_text(encoding="utf-8"), path
        assert "from WinUx" not in path.read_text(encoding="utf-8"), path
    for path in (ROOT / "WinUx").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "DearUIQt.qt" not in source, path


def test_winux_migration_wave_replaces_main_panel_native_containers():
    view = (ROOT / "WinUx" / "view.py").read_text(encoding="utf-8")
    file_panel = (ROOT / "WinUx" / "ui" / "components" / "file_panel.py").read_text(encoding="utf-8")
    jobs = (ROOT / "WinUx" / "ui" / "components" / "jobs_view.py").read_text(encoding="utf-8")
    assert "self._layout_root_frame = QFrame" in view
    assert "self._file_status_frame = QFrame" in view
    assert "self._container_widget = QFrame" in file_panel
    assert "self._container_widget = QFrame" in jobs
    # Common retained widget/layout constructors now belong to DearUIQt.
    # Low-level drawing/table/plot primitives intentionally remain backend APIs.
    constructors = (
        "add_child_window", "add_group", "add_text", "add_spacer",
        "add_separator", "add_button", "add_image_button", "add_input_text",
        "add_checkbox",
    )
    sources = [path.read_text(encoding="utf-8") for path in (ROOT / "WinUx").rglob("*.py")]
    for constructor in constructors:
        assert all(("dpg." + constructor + "(") not in source for source in sources), constructor
