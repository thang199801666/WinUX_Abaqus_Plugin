from DearUIQt.gui import QBrush, QPainter, QPen
from DearUIQt.widgets import QCanvas


class FakeBackend:
    def __init__(self):
        self.next = 100
        self.existing = set()
        self.calls = []

    def _new(self, kind, *args, **kwargs):
        tag = kwargs.get("tag") or self.next
        self.next += 1
        self.existing.add(tag)
        self.calls.append((kind, args, kwargs, tag))
        return tag

    def add_drawlist(self, *args, **kwargs):
        return self._new("drawlist", *args, **kwargs)

    def draw_line(self, *args, **kwargs):
        return self._new("line", *args, **kwargs)

    def draw_rectangle(self, *args, **kwargs):
        return self._new("rect", *args, **kwargs)

    def draw_circle(self, *args, **kwargs):
        return self._new("circle", *args, **kwargs)

    def draw_triangle(self, *args, **kwargs):
        return self._new("triangle", *args, **kwargs)

    def draw_quad(self, *args, **kwargs):
        return self._new("quad", *args, **kwargs)

    def draw_polygon(self, *args, **kwargs):
        return self._new("polygon", *args, **kwargs)

    def draw_text(self, *args, **kwargs):
        return self._new("text", *args, **kwargs)

    def draw_image(self, *args, **kwargs):
        return self._new("image", *args, **kwargs)

    def bind_item_font(self, item, font):
        self.calls.append(("font", (item, font), {}, None))

    def does_item_exist(self, tag):
        return tag in self.existing

    def configure_item(self, tag, **kwargs):
        self.calls.append(("configure", (tag,), kwargs, None))

    def delete_item(self, tag, **kwargs):
        self.calls.append(("delete", (tag,), kwargs, None))
        if not kwargs.get("children_only"):
            self.existing.discard(tag)


def test_qcanvas_owns_drawlist_and_clear_keeps_surface_alive():
    backend = FakeBackend()
    canvas = QCanvas(320, 180, backend=backend, tag="canvas")
    assert canvas.tag == "canvas"
    assert canvas.isVisible()
    assert backend.calls[0][0] == "drawlist"
    assert backend.calls[0][2]["width"] == 320
    assert backend.calls[0][2]["height"] == 180
    assert canvas.clear() is True
    assert backend.calls[-1][:3] == ("delete", ("canvas",), {"children_only": True})
    assert backend.does_item_exist("canvas")


def test_qpainter_maps_stateful_pen_brush_and_retains_native_ids():
    backend = FakeBackend()
    canvas = QCanvas(100, 80, backend=backend)
    painter = QPainter(canvas)
    painter.setPen(QPen((1, 2, 3, 255), 2.5))
    painter.setBrush(QBrush((4, 5, 6, 128)))
    rect = painter.drawRect((1, 2), (30, 40), rounding=3)
    line = painter.drawLine((0, 0), (3, 4))
    assert rect != line
    rect_call = next(call for call in backend.calls if call[0] == "rect")
    assert rect_call[2]["parent"] == canvas.tag
    assert rect_call[2]["color"] == (1, 2, 3, 255)
    assert rect_call[2]["fill"] == (4, 5, 6, 128)
    assert rect_call[2]["thickness"] == 2.5


def test_qpainter_text_font_binding_and_image_uv_are_renderer_details():
    backend = FakeBackend()
    canvas = QCanvas(100, 80, backend=backend)
    painter = canvas.painter()
    text = painter.drawText((5, 6), "hello", color=(9, 8, 7, 255), size=14, font="body")
    image = painter.drawImage("texture", (0, 0), (20, 20), uv_min=(.1, .2), uv_max=(.8, .9))
    assert ("font", (text, "body"), {}, None) in backend.calls
    image_call = next(call for call in backend.calls if call[0] == "image")
    assert image_call[3] == image
    assert image_call[2]["uv_min"] == (.1, .2)
    assert image_call[2]["uv_max"] == (.8, .9)
