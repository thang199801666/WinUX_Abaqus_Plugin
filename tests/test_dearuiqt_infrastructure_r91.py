import ast
from pathlib import Path

from DearUIQt.core import Qt
from DearUIQt.gui import QCursor, QKeyboard, QTextureRegistry
from DearUIQt.runtime import QGuiRuntime
from DearUIQt.widgets import QRetainedItem


class FakeBackend:
    mvMouseButton_Left = 0
    mvMouseButton_Right = 1
    mvMouseButton_Middle = 2
    mvKey_Escape = 256

    def __init__(self):
        self.items = {
            10: {"parent": 1, "pos": (5, 6), "size": (40, 20), "show": True},
            20: {"parent": 1, "pos": (0, 0), "size": (10, 10), "show": True},
            30: {"popup": True, "show": False},
            31: {"modal": True, "show": True},
        }
        self.moved = []
        self.deleted = []
        self.next_frame = None
        self.frame = 7
        self.clicked = {self.mvMouseButton_Left}
        self.double_clicked = {self.mvMouseButton_Left}
        self.pressed_keys = {self.mvKey_Escape}
        self._next = 100

    def does_item_exist(self, tag):
        return tag in self.items

    def get_item_parent(self, tag):
        return self.items[tag].get("parent")

    def get_item_pos(self, tag):
        return self.items[tag].get("pos", (0, 0))

    def get_item_rect_min(self, tag):
        return self.items[tag].get("pos", (0, 0))

    def get_item_rect_size(self, tag):
        return self.items[tag].get("size", (0, 0))

    def get_item_configuration(self, tag):
        return dict(self.items[tag])

    def get_item_state(self, tag):
        return {}

    def is_item_shown(self, tag):
        return bool(self.items[tag].get("show", True))

    def move_item(self, tag, **kwargs):
        self.moved.append((tag, dict(kwargs)))
        if "parent" in kwargs:
            self.items[tag]["parent"] = kwargs["parent"]

    def configure_item(self, tag, **kwargs):
        self.items[tag].update(kwargs)

    def delete_item(self, tag, children_only=False):
        if not children_only:
            self.deleted.append(tag)
            self.items.pop(tag, None)

    def is_mouse_button_clicked(self, button):
        return button in self.clicked

    def is_mouse_button_double_clicked(self, button):
        return button in self.double_clicked

    def is_mouse_button_down(self, button):
        return button in self.clicked

    def is_key_pressed(self, key):
        return key in self.pressed_keys

    def get_mouse_pos(self, local=False):
        return (12, 13) if not local else (2, 3)

    def get_frame_count(self):
        return self.frame

    def set_frame_callback(self, frame, callback=None):
        self.next_frame = (frame, callback)

    def get_windows(self):
        return [30, 31]

    # QTextureRegistry support
    class _Registry:
        def __init__(self, owner):
            self.owner = owner
            self.tag = None
        def __enter__(self):
            self.owner._next += 1
            self.tag = self.owner._next
            self.owner.items[self.tag] = {"show": False}
            return self.tag
        def __exit__(self, *args):
            return False

    def texture_registry(self, show=False):
        return self._Registry(self)

    def load_image(self, path):
        return 1, 1, 4, [1.0, 0.5, 0.25, 1.0]

    def add_static_texture(self, width, height, data, parent=None, tag=None):
        native = tag or (self._next + 1)
        if tag is None:
            self._next += 1
        self.items[native] = {"size": (width, height), "parent": parent, "data": data}
        return native


def test_retained_reparent_and_frame_input_helpers_are_backend_neutral(tmp_path):
    backend = FakeBackend()
    item = QRetainedItem(10, backend=backend)
    assert item.reparent(20)
    assert backend.items[10]["parent"] == 20
    item.setLabel("renamed").setTexture("texture")
    assert backend.items[10]["label"] == "renamed"
    assert backend.items[10]["texture_tag"] == "texture"

    assert QCursor.isButtonClicked(Qt.LeftButton, backend=backend)
    assert QCursor.isButtonDoubleClicked(Qt.LeftButton, backend=backend)
    assert QKeyboard.isKeyPressed(Qt.Key_Escape, backend=backend)

    runtime = QGuiRuntime(backend)
    called = []
    assert runtime.invokeNextFrame(lambda: called.append(True))
    assert backend.next_frame[0] == 8
    backend.next_frame[1]()
    assert called == [True]
    assert runtime.hasActivePopupSurface()

    image = tmp_path / "icon.png"
    image.write_bytes(b"not-decoded-by-fake")
    textures = QTextureRegistry(backend=backend)
    texture = textures.loadFile(image, tag="icon")
    assert texture is not None and texture.nativeId() == "icon"
    assert backend.items["icon"]["size"] == (1, 1)


def test_r91_migrated_infrastructure_has_no_direct_dpg_attribute_calls():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "WinUx/ui/behaviors/plot_docking.py",
        root / "WinUx/ui/components/explorer_layout.py",
        root / "WinUx/dialogs/local_folder_form.py",
        root / "WinUx/ui/components/toolbar.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "dpg"
        ]
        assert not calls, path


def test_folder_row_router_preserves_full_row_semantics_after_backend_migration():
    from DearUIQt.core import QRect
    from WinUx.dialogs.local_folder_form import FolderListView

    class View:
        _deleted = False
        items = {"A": 101, "B": 102}
        backend = None

        def __init__(self):
            self.clicked = []

        def isVisible(self):
            return True

        def globalGeometry(self, clipped=False):
            del clipped
            return QRect(100, 100, 400, 180)

        def itemGeometry(self, key, include_check_indicator=False):
            del include_check_indicator
            return QRect(100, 120 if key == "A" else 144, 400, 24)

        def _clicked(self, sender, value, key):
            self.clicked.append((sender, value, key))

    view = View()
    assert FolderListView._row_pointer_clicked(view, point=(360, 125)) is True
    assert view.clicked == [(101, True, "A")]
    assert FolderListView._row_pointer_clicked(view, point=(360, 175)) is None
    assert view.clicked == [(101, True, "A")]


def test_runtime_supports_multi_frame_focus_retry_without_backend_leakage():
    backend = FakeBackend()
    runtime = QGuiRuntime(backend)
    one, two = [], []
    assert runtime.invokeAfterFrames(lambda: one.append(True), 1)
    first = backend.next_frame
    assert first[0] == 8
    assert runtime.invokeAfterFrames(lambda: two.append(True), 2)
    second = backend.next_frame
    assert second[0] == 9
    first[1]()
    second[1]()
    assert one == [True] and two == [True]


def test_atomic_plot_handoff_uses_retained_visibility_boundary():
    source = (Path(__file__).resolve().parents[1] /
              "WinUx/ui/behaviors/plot_docking.py").read_text(encoding="utf-8")
    undock = source.split("def undock_job_plots(", 1)[1].split("def dock_job_plots(", 1)[0]
    dock = source.split("def dock_job_plots(", 1)[1].split("def ", 1)[0]
    assert "QRetainedItem(panel.root).hide()" in undock
    assert "QRetainedItem(window.root).show()" in dock
    assert "host.after_first_present(commit_float)" in undock


def test_r91_global_backend_boundary_and_dependency_direction():
    root = Path(__file__).resolve().parents[1]
    total = 0
    files = 0
    direct_renderer_imports = []
    for path in (root / "WinUx").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "dpg"
        )
        if count:
            total += count
            files += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.startswith("dearpygui") for alias in node.names):
                    direct_renderer_imports.append(path)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("dearpygui"):
                    direct_renderer_imports.append(path)
    assert not direct_renderer_imports
    assert total <= 489
    assert files <= 36

    reverse_imports = []
    for path in (root / "DearUIQt").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.startswith("WinUx") for alias in node.names):
                    reverse_imports.append(path)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("WinUx"):
                    reverse_imports.append(path)
    assert not reverse_imports
