from contextlib import contextmanager
from pathlib import Path

from DearUIQt.core import Qt, QObject, QGlobalInputBinding, QItemInputBinding
from DearUIQt.gui import QCursor
from DearUIQt.themes import QTheme


class _Backend:
    mvKey_A = 65
    mvMouseButton_Left = 0
    mvMouseButton_Right = 1
    mvMouseButton_Middle = 2

    def __init__(self):
        self.deleted = []
        self.key_handlers = []
        self.mouse_handlers = []
        self.item_handlers = []
        self.bound_registry = None
        self.down = {self.mvMouseButton_Right}
        self._next = 100

    def does_item_exist(self, item):
        return item not in self.deleted

    def delete_item(self, item):
        self.deleted.append(item)

    def is_mouse_button_down(self, button):
        return button in self.down

    def _id(self):
        self._next += 1
        return self._next

    @contextmanager
    def handler_registry(self):
        yield self._id()

    @contextmanager
    def item_handler_registry(self):
        yield self._id()

    def add_key_press_handler(self, **kwargs):
        self.key_handlers.append(kwargs)

    def add_mouse_click_handler(self, **kwargs):
        self.mouse_handlers.append(("click", kwargs))

    def add_mouse_release_handler(self, **kwargs):
        self.mouse_handlers.append(("release", kwargs))

    def add_mouse_drag_handler(self, **kwargs):
        self.mouse_handlers.append(("drag", kwargs))

    def add_mouse_wheel_handler(self, **kwargs):
        self.mouse_handlers.append(("wheel", kwargs))

    def add_item_clicked_handler(self, **kwargs):
        self.item_handlers.append(("click", kwargs))

    def add_item_hover_handler(self, **kwargs):
        self.item_handlers.append(("hover", kwargs))

    def bind_item_handler_registry(self, target, registry):
        self.bound_registry = (target, registry)


def test_qtheme_owns_native_theme_lifetime():
    backend = _Backend()
    parent = QObject()
    theme = QTheme(theme_id=42, backend=backend, parent=parent)
    assert theme.nativeId() == 42
    assert theme.exists()
    parent.delete()
    assert 42 in backend.deleted


def test_qcursor_mouse_buttons_are_qt_flags_without_qapplication():
    backend = _Backend()
    assert QCursor.buttons(backend=backend) == Qt.RightButton
    assert QCursor.isButtonDown(Qt.RightButton, backend=backend)
    assert not QCursor.isButtonDown(Qt.LeftButton, backend=backend)


def test_global_input_binding_translates_qt_keys_and_owns_registry():
    backend = _Backend()
    binding = QGlobalInputBinding(backend=backend)
    callback = lambda *_args: None
    binding.onKeyPress(Qt.Key_A, callback)
    binding.onMouseClick(Qt.RightButton, callback)
    binding.activate()
    assert backend.key_handlers[0]["key"] == backend.mvKey_A
    assert backend.mouse_handlers[0][1]["button"] == backend.mvMouseButton_Right
    registry = binding._registry
    binding.delete()
    assert registry in backend.deleted


def test_item_input_binding_keeps_registry_inside_dearuiqt():
    backend = _Backend()
    binding = QItemInputBinding("canvas", backend=backend)
    binding.onClick(Qt.LeftButton, lambda *_args: None).onHover(lambda *_args: None)
    binding.activate()
    assert backend.bound_registry[0] == "canvas"
    assert backend.item_handlers[0][1]["button"] == backend.mvMouseButton_Left
    registry = binding._registry
    binding.delete()
    assert registry in backend.deleted



def test_item_input_binding_drops_callback_after_target_is_deleted():
    backend = _Backend()
    seen = []
    binding = QItemInputBinding("canvas", backend=backend)
    binding.onHover(lambda *args: seen.append(args)).activate()
    callback = backend.item_handlers[-1][1]["callback"]
    callback("handler", None, None)
    assert len(seen) == 1
    backend.deleted.append("canvas")
    callback("handler", None, None)
    assert len(seen) == 1


def test_item_input_binding_drops_already_queued_callback_after_delete():
    backend = _Backend()
    seen = []
    binding = QItemInputBinding("canvas", backend=backend)
    binding.onHover(lambda *args: seen.append(args)).activate()
    callback = backend.item_handlers[-1][1]["callback"]
    binding.delete()
    callback("handler", None, None)
    assert seen == []

def test_console_uses_dearuiqt_modeless_and_input_contracts():
    root = Path(__file__).resolve().parents[1]
    source = (root / "WinUx" / "dialogs" / "console_form.py").read_text(encoding="utf-8")
    assert "QModelessMenu" in source
    assert "QGlobalInputBinding" in source
    assert "QItemInputBinding" in source
    assert "QTheme" in source
    assert "dpg.handler_registry" not in source
    assert "dpg.item_handler_registry" not in source
    assert "dpg.bind_item_theme" not in source


def test_explorer_input_shield_is_a_dearuiqt_popup_panel():
    root = Path(__file__).resolve().parents[1]
    source = (root / "WinUx" / "ui" / "components" / "explorer_context_menu.py").read_text(encoding="utf-8")
    # The input shield and the application popup grab now live in the
    # DearUIQt QMenu; the Explorer keeps only compatibility delegates.
    assert "_input_shield_tag" in source
    shield = source.split("def _ensure_context_input_shield", 1)[1].split("def _acquire_context_popup_input", 1)[0]
    assert "menu._show_input_shield()" in shield
    assert "menu._hide_input_shield()" in shield
    assert "QMenu.popup() owns the application popup grab" in source
