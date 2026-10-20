import ast
from pathlib import Path

from DearUIQt.runtime import QGuiRuntime
from DearUIQt.widgets import QRetainedItem


class FakeBackend:
    def __init__(self):
        self.items = {
            1: {"type": "mvAppItemType::mvTheme", "parent": None, "min_size": (320, 180)},
            2: {"type": "mvAppItemType::mvTheme", "parent": None},
            3: {"type": "mvAppItemType::mvButton", "parent": None},
            4: {"type": "mvAppItemType::mvTheme", "parent": 3},
        }
        self.deleted = []

    def does_item_exist(self, tag):
        return tag in self.items

    def get_item_configuration(self, tag):
        return dict(self.items[tag])

    def get_all_items(self):
        return list(self.items)

    def get_item_info(self, tag):
        item = self.items[tag]
        return {"type": item.get("type"), "parent": item.get("parent")}

    def delete_item(self, tag, children_only=False):
        if not children_only:
            self.deleted.append(tag)
            self.items.pop(tag, None)


def _direct_dpg_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "dpg"
    )


def _backend_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("DearUIQt.backends")
    ]


def test_retained_configuration_snapshot_hides_renderer_configuration_query():
    backend = FakeBackend()
    retained = QRetainedItem(1, backend=backend)
    assert retained.nativeConfiguration()["min_size"] == (320, 180)


def test_runtime_owns_reusable_host_item_snapshot_and_resource_cleanup():
    backend = FakeBackend()
    runtime = QGuiRuntime(backend)
    snapshot = runtime.itemSnapshot()
    assert snapshot == frozenset({1, 2, 3, 4})
    assert runtime.itemCount() == 4

    backend.items[5] = {"type": "mvAppItemType::mvTheme", "parent": None}
    backend.items[6] = {"type": "mvAppItemType::mvButton", "parent": None}
    backend.items[7] = {"type": "mvAppItemType::mvTheme", "parent": 6}

    assert runtime.releaseTopLevelItemsSince(
        snapshot, item_type="mvAppItemType::mvTheme") == 1
    assert 5 in backend.deleted
    assert 6 in backend.items and 7 in backend.items


def test_r93_migrated_hotspots_use_only_public_dearuiqt_boundaries():
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "WinUx/ui/components/job_plots.py",
        root / "WinUx/ui/hosting/floating_runtime.py",
        root / "WinUx/ui/components/explorer_rubber_band.py",
        root / "WinUx/ui/components/jobs_view.py",
        root / "WinUx/plotdigitizer/standalone.py",
        root / "WinUx/plotdigitizer/ui/dialog.py",
        root / "WinUx/dialogs/odb_check_form.py",
        root / "WinUx/ui/appearance.py",
    ]
    for path in paths:
        assert _direct_dpg_calls(path) == 0, path
        assert not _backend_imports(path), path


def test_r93_global_direct_backend_boundary_is_below_200_calls():
    root = Path(__file__).resolve().parents[1]
    total = 0
    files = 0
    backend_import_files = 0
    for path in (root / "WinUx").rglob("*.py"):
        count = _direct_dpg_calls(path)
        if count:
            total += count
            files += 1
        if _backend_imports(path):
            backend_import_files += 1
    assert total <= 187
    assert files <= 24
    assert backend_import_files <= 25
