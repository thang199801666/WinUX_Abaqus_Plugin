from DearUIQt.widgets import QMenu


class _BackendStub:
    def __init__(self):
        self.deleted = []
        self.triangles = []

    def delete_item(self, item, children_only=False):
        self.deleted.append((item, children_only))

    def draw_triangle(self, p1, p2, p3, **kwargs):
        self.triangles.append((p1, p2, p3, kwargs))


def test_qmenu_submenu_arrow_uses_filled_triangle_geometry():
    menu = object.__new__(QMenu)
    menu.backend = _BackendStub()
    menu._arrow_offsets = {"canvas": 100.0}

    menu._redraw_submenu_arrow("canvas", visible=True, enabled=True)

    assert menu.backend.deleted == [("canvas", True)]
    assert len(menu.backend.triangles) == 1
    p1, p2, p3, kwargs = menu.backend.triangles[0]
    assert (p1, p2, p3) == ((106.0, 8), (112.0, 12), (106.0, 16))
    assert kwargs["parent"] == "canvas"
    assert kwargs["color"] == kwargs["fill"]
    assert kwargs["thickness"] == 1.0


def test_qmenu_submenu_arrow_skips_hidden_rows():
    menu = object.__new__(QMenu)
    menu.backend = _BackendStub()
    menu._arrow_offsets = {}

    menu._redraw_submenu_arrow("canvas", visible=False, enabled=True)

    assert menu.backend.deleted == [("canvas", True)]
    assert menu.backend.triangles == []
