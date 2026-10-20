from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class FakeBackend:
    def __init__(self):
        self.next = 100
        self.config = {}
        self.values = {}
        self.x_scroll = {}
        self.y_scroll = {}
        self.x_max = {}
        self.y_max = {}

    def _new(self, **kwargs):
        tag = self.next
        self.next += 1
        self.config[tag] = dict(kwargs)
        self.values[tag] = kwargs.get("default_value")
        self.x_scroll[tag] = 0
        self.y_scroll[tag] = 0
        self.x_max[tag] = 400
        self.y_max[tag] = 500
        return tag

    def add_child_window(self, **kwargs): return self._new(**kwargs)
    def add_window(self, **kwargs): return self._new(**kwargs)
    def add_group(self, **kwargs): return self._new(**kwargs)
    def add_text(self, *args, **kwargs): return self._new(**kwargs)
    def add_spacer(self, **kwargs): return self._new(**kwargs)
    def add_separator(self, **kwargs): return self._new(**kwargs)
    def does_item_exist(self, tag): return tag in self.config
    def configure_item(self, tag, **kwargs): self.config.setdefault(tag, {}).update(kwargs)
    def delete_item(self, tag): self.config.pop(tag, None)
    def set_value(self, tag, value): self.values[tag] = value
    def get_value(self, tag): return self.values.get(tag)
    def get_item_configuration(self, tag): return self.config.get(tag, {})
    def get_item_state(self, tag): return {}
    def get_item_parent(self, tag): return 1
    def move_item(self, tag, **kwargs):
        self.config.setdefault(tag, {}).update({k: v for k, v in kwargs.items() if k in ("parent", "before")})
        return None
    def get_x_scroll(self, tag): return self.x_scroll.get(tag, 0)
    def get_y_scroll(self, tag): return self.y_scroll.get(tag, 0)
    def get_x_scroll_max(self, tag): return self.x_max.get(tag, 0)
    def get_y_scroll_max(self, tag): return self.y_max.get(tag, 0)
    def set_x_scroll(self, tag, value): self.x_scroll[tag] = int(value)
    def set_y_scroll(self, tag, value): self.y_scroll[tag] = int(value)


def test_r76_version_and_winux_renderer_imports_are_centralized():
    import DearUIQt
    assert tuple(map(int, DearUIQt.__version__.split("."))) >= (1, 15, 0)
    offenders = []
    for path in (ROOT / "WinUx").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "import dearpygui" in source or "from dearpygui" in source:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_backend_capability_contract_is_renderer_neutral():
    from DearUIQt.backends import backend_capabilities, require_backend_capability
    backend = FakeBackend()
    caps = backend_capabilities(backend)
    assert caps.retained_items and caps.windows and caps.child_windows
    assert caps.scrolling
    assert not caps.plots
    assert require_backend_capability(backend, "retained_items", "scrolling") == caps


def test_qpalette_qstyle_and_application_widget_inheritance_remain_backend_lazy():
    for name in list(sys.modules):
        if name.startswith("dearpygui"):
            sys.modules.pop(name, None)
    from DearUIQt.gui import QPalette, QStyle, QProxyStyle, QStyleFactory
    from DearUIQt.widgets import QApplication, QWidget

    palette = QPalette.fusion()
    assert palette.color(QPalette.Text) is not None
    changed = palette.copy()
    changed.setColor(QPalette.Text, (1, 2, 3))
    assert changed.color(QPalette.Text) == (1, 2, 3, 255)
    assert palette.color(QPalette.Text) != changed.color(QPalette.Text)

    fusion = QStyleFactory.create("Fusion")
    assert isinstance(fusion, QStyle)
    proxy = QProxyStyle(fusion)
    assert proxy.pixelMetric(QStyle.PM_SplitterWidth) == fusion.pixelMetric(QStyle.PM_SplitterWidth)

    app = QApplication()
    try:
        app.setStyle(proxy)
        app.setPalette(changed)
        widget = QWidget(tag=1, backend=FakeBackend())
        assert widget.style() is proxy
        assert widget.palette().color(QPalette.Text) == (1, 2, 3, 255)
        widget.setPalette(palette)
        assert widget.palette() == palette
        widget.unsetPalette()
        assert widget.palette() == changed
    finally:
        app.delete()
    assert "dearpygui.dearpygui" not in sys.modules


def test_qabstractscrollarea_exposes_qt_policies_without_fake_visual_scrollbars():
    from DearUIQt.core import Qt
    from DearUIQt.widgets import QAbstractScrollArea, QScrollArea
    backend = FakeBackend()
    area = QScrollArea(
        backend=backend,
        horizontal_scrollbar=False,
        vertical_scrollbar=True,
    )
    assert isinstance(area, QAbstractScrollArea)
    assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert area.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert backend.config[area.tag]["horizontal_scrollbar"] is False
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    assert backend.config[area.tag]["horizontal_scrollbar"] is True
    area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    assert backend.config[area.tag]["no_scrollbar"] is True

    hbar = area.horizontalScrollBar()
    vbar = area.verticalScrollBar()
    hbar.setValue(25)
    vbar.setValue(35)
    assert (hbar.value(), vbar.value()) == (25, 35)
    area.scrollContentsBy(10, 15)
    assert (hbar.value(), vbar.value()) == (35, 50)
    area.setViewportMargins(1, 2, 3, 4)
    assert tuple(area.viewportMargins()) == (1, 2, 3, 4)


def test_qmainwindow_owns_menu_toolbar_and_statusbar_as_library_components():
    from DearUIQt.widgets import QMainWindow, QMenuBar, QToolBar, QStatusBar
    backend = FakeBackend()
    window = QMainWindow("Library shell", backend=backend)
    menu = QMenuBar(backend=backend)
    window.setMenuBar(menu)
    toolbar = QToolBar("Main", backend=backend)
    window.addToolBar(toolbar)
    status = QStatusBar(backend=backend)
    window.setStatusBar(status)
    assert window.menuBar() is menu
    assert window.toolBars() == (toolbar,)
    assert window.statusBar() is status
    assert menu.parent is window and toolbar.parent is window and status.parent is window
    window.setWindowTitle("Renamed")
    assert window.windowTitle() == "Renamed"


def test_dialog_forms_use_dearuiqt_state_facade_instead_of_renderer_value_calls():
    settings = (ROOT / "WinUx/dialogs/settings_form.py").read_text(encoding="utf-8")
    sites = (ROOT / "WinUx/dialogs/site_manager_form.py").read_text(encoding="utf-8")
    for source in (settings, sites):
        assert "dpg.get_value(" not in source
        assert "dpg.set_value(" not in source
    assert "self.control_value(" in settings
    assert "self.set_control_value(" in settings
    assert "self.set_control_items(" in sites
    assert "self.focus_control(" in sites
