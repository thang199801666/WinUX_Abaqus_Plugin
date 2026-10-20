from pathlib import Path
from types import SimpleNamespace

from WinUx.ui.components.explorer_rendering import ExplorerRenderingMixin
from WinUx.ui.components.explorer_row_registry import ExplorerRowRegistryMixin


class _RenderHarness:
    _bind_body_row = ExplorerRenderingMixin._bind_body_row

    def __init__(self, fill):
        self.items = [SimpleNamespace(data={"row_fill": fill})]
        self._item_icons = {}

    def _visible_columns(self):
        return []

    def _retained_item(self, tag):
        raise AssertionError("no retained native item should be needed in this harness")


class _RegistryHarness:
    _refresh_row_registry_content = ExplorerRowRegistryMixin._refresh_row_registry_content

    def __init__(self):
        self.items = [object(), object()]
        self._row_items = [{"index": 0}, {"index": 1}]

    def _bind_body_row(self, row, index, preserve_geometry=False):
        row["content_changed"] = index == 1


def _row(fill):
    return {
        "index": 0,
        "item_object_id": None,
        "row_fill": fill,
        "content_changed": False,
        "visual_signature": ("cached",),
        "visual_background_signature": ("cached",),
        "visual_text_color": (1, 2, 3, 255),
        "selection_inner": None,
        "values": {},
        "texts": {},
        "icon": None,
    }


def test_row_fill_change_marks_reused_row_as_changed_and_invalidates_background_cache():
    old_fill = None
    running_fill = (205, 244, 213, 255)
    view = _RenderHarness(running_fill)
    row = _row(old_fill)

    view._bind_body_row(row, 0, preserve_geometry=True)

    assert row["row_fill"] == running_fill
    assert row["content_changed"] is True
    assert row["visual_background_signature"] is None


def test_unchanged_row_fill_does_not_force_content_refresh():
    running_fill = (205, 244, 213, 255)
    view = _RenderHarness(running_fill)
    item = view.items[0]
    row = _row(running_fill)
    row["item_object_id"] = id(item)

    view._bind_body_row(row, 0, preserve_geometry=True)

    assert row["content_changed"] is False


def test_row_registry_reports_only_rows_whose_content_or_visual_state_changed():
    view = _RegistryHarness()
    assert view._refresh_row_registry_content() == {1}


def test_reused_listview_rows_explicitly_repaint_changed_visual_indices():
    source = (Path(__file__).resolve().parents[1] / "WinUx" / "ui" / "components" / "explorer_list_view.py").read_text(encoding="utf-8")
    assert "changed = self._refresh_row_content()" in source
    assert "self._update_selection_draws(indices=set(changed))" in source


def test_refresh_row_visuals_invalidates_background_cache_and_repaints_targets():
    class _View:
        refresh_row_visuals = ExplorerRenderingMixin.refresh_row_visuals

        def __init__(self):
            self.items = [object(), object()]
            self.rows = {
                0: {"visual_background_signature": ("stale",), "visual_signature": ("stale",)},
                1: {"visual_background_signature": ("stale",), "visual_signature": ("stale",)},
            }
            self.updated = None

        def _rendered_row_indices(self):
            return (0, 1)

        def _row_for_index(self, index):
            return self.rows.get(index)

        def _update_selection_draws(self, indices=None, force=False):
            self.updated = set(indices or ())

    view = _View()
    assert view.refresh_row_visuals() == {0, 1}
    assert view.updated == {0, 1}
    assert view.rows[0]["visual_background_signature"] is None
    assert view.rows[1]["visual_background_signature"] is None
    assert view.rows[0]["visual_signature"] is None
    assert view.rows[1]["visual_signature"] is None


def test_jobs_view_display_forces_status_row_colors_without_waiting_for_hover():
    from WinUx.ui.components.jobs_view import JobsView

    class _FakeListView:
        def __init__(self):
            self.items = []
            self.refresh_calls = 0

        def get_selected(self):
            return []

        def set_items(self, items):
            self.items = list(items)

        def select_indices(self, indices):
            raise AssertionError("no selection should be restored in this test")

        def refresh_row_visuals(self):
            self.refresh_calls += 1

    job = SimpleNamespace(
        job_id="31646", name="29-20260030-1-1-1-1C", user="huyhuynh",
        tokens="32", status="Running", elapsed="00:30:18",
    )
    view = JobsView.__new__(JobsView)
    view.listview = _FakeListView()

    view.display([job])

    assert view.listview.refresh_calls == 1
    assert view.listview.items[0].data["row_fill"] == (205, 244, 213, 255)
