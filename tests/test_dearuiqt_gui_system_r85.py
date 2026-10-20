from DearUIQt.core import QPoint, QRect, QSize, Qt
from DearUIQt.gui import QClipboard, QCursor, QKeyboard, QFontMetrics, QScreen
from DearUIQt.widgets import QCanvas


class FakeBackend:
    mvMouseCursor_Arrow = 1
    mvMouseCursor_ResizeEW = 2
    mvMouseCursor_ResizeNS = 3
    mvMouseCursor_ResizeNWSE = 4
    mvMouseCursor_ResizeNESW = 5
    mvMouseCursor_Hand = 6
    mvMouseCursor_TextInput = 7
    mvMouseButton_Left = 10
    mvMouseButton_Right = 11
    mvMouseButton_Middle = 12
    mvKey_LShift = 20
    mvKey_RShift = 21
    mvKey_LControl = 22
    mvKey_RControl = 23
    mvKey_LAlt = 24
    mvKey_RAlt = 25
    mvKey_LWin = 26
    mvKey_RWin = 27

    def __init__(self):
        self.cursor = None
        self.clipboard = "seed"
        self.existing = set()
        self.next = 100
        self.theme_bindings = []
        self.keys_down = set()

    def get_mouse_pos(self, local=False):
        return (11, 22) if local else (111, 222)

    def is_key_down(self, key):
        return key in self.keys_down

    def get_mouse_drag_delta(self, button=None):
        assert button in (None, self.mvMouseButton_Left)
        return (7, -3)

    def set_mouse_cursor(self, cursor):
        self.cursor = cursor

    def get_clipboard_text(self):
        return self.clipboard

    def set_clipboard_text(self, text):
        self.clipboard = text

    def get_text_size(self, text, **kwargs):
        return (len(text) * 8, 17)

    def get_viewport_pos(self):
        return (30, 40)

    def get_viewport_client_width(self):
        return 900

    def get_viewport_client_height(self):
        return 600

    def get_viewport_width(self):
        return 940

    def get_viewport_height(self):
        return 660

    def add_drawlist(self, width=-1, height=-1, **kwargs):
        tag = kwargs.get("tag", self.next)
        self.next += 1
        self.existing.add(tag)
        return tag

    def does_item_exist(self, tag):
        return tag in self.existing

    def configure_item(self, tag, **kwargs):
        pass

    def delete_item(self, tag, **kwargs):
        if not kwargs.get("children_only"):
            self.existing.discard(tag)

    def bind_item_theme(self, tag, theme):
        self.theme_bindings.append((tag, theme))

    def is_item_hovered(self, tag):
        return tag in self.existing

    def get_item_state(self, tag):
        return {"active": tag in self.existing}

    def get_item_rect_min(self, tag):
        return (15, 25)

    def get_item_rect_size(self, tag):
        return (320, 180)

    def get_item_parent(self, tag):
        return 42


def test_cursor_clipboard_font_metrics_and_screen_hide_renderer_queries():
    backend = FakeBackend()
    assert QCursor.pos(backend=backend) == QPoint(111, 222)
    assert QCursor.localPos(backend=backend) == QPoint(11, 22)
    assert QCursor.dragDelta(backend=backend) == QPoint(7, -3)
    assert QCursor.setShape(QCursor.SizeHorCursor, backend=backend)
    assert backend.cursor == backend.mvMouseCursor_ResizeEW
    backend.keys_down.update((backend.mvKey_LControl, backend.mvKey_RShift))
    assert QKeyboard.modifiers(backend=backend) == (Qt.ControlModifier | Qt.ShiftModifier)

    clipboard = QClipboard(backend=backend)
    assert clipboard.text() == "seed"
    assert clipboard.setText("abc")
    assert clipboard.text() == "abc"

    metrics = QFontMetrics(backend=backend)
    assert metrics.horizontalAdvance("abcd") == 32
    assert metrics.height() == 17
    assert metrics.size("abc") == QSize(24, 17)

    screen = QScreen(backend=backend)
    assert screen.geometry() == QRect(30, 40, 900, 600)
    assert screen.size() == QSize(900, 600)
    assert screen.windowGeometry() == QRect(30, 40, 940, 660)


def test_qwidget_exposes_theme_hover_active_and_global_geometry_contract():
    backend = FakeBackend()
    canvas = QCanvas(320, 180, backend=backend, tag="canvas")
    assert canvas.exists()
    assert canvas.setTheme("fusion")
    assert canvas.theme() == "fusion"
    assert backend.theme_bindings == [("canvas", "fusion")]
    assert canvas.underMouse()
    assert canvas.isActive()
    assert canvas.globalPos() == QPoint(15, 25)
    assert canvas.globalGeometry() == QRect(15, 25, 320, 180)
    assert canvas.nativeParentId() == 42
