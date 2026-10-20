from pathlib import Path
import tempfile

from WinUx.services.reference_charts import ReferenceChartLibrary, ReferenceTableModel

ROOT = Path(__file__).resolve().parents[1]


class CountingPoints:
    def __init__(self, count):
        self.count = int(count)
        self.reads = 0

    def __len__(self):
        return self.count

    def __getitem__(self, index):
        if isinstance(index, slice):
            start, stop, step = index.indices(self.count)
            return [self[i] for i in range(start, stop, step)]
        if index < 0:
            index += self.count
        if not 0 <= index < self.count:
            raise IndexError(index)
        self.reads += 1
        return [float(index), float(index * 2)]


def test_large_reference_load_is_lazy_and_reads_only_visible_rows():
    points = CountingPoints(250_000)
    model = ReferenceTableModel()
    model.load_series([{"name": "Huge", "points": points}])

    assert model.row_count == 250_000
    assert model._source_points is points
    assert points.reads == 0

    first_page = model.cells[:50]
    assert len(first_page) == 50
    assert first_page[0] == ["0", "0"]
    assert first_page[-1] == ["49", "98"]
    # One source-row read is enough to format both X/Y cells in normal page use.
    # The compatibility row sequence may access a row twice, but must remain
    # bounded by the visible page instead of total dataset size.
    assert points.reads <= 100


def test_sparse_edits_do_not_mutate_borrowed_points():
    points = [[float(i), float(i * 2)] for i in range(1000)]
    model = ReferenceTableModel()
    model.load_series([{"name": "Large", "points": points}])
    model.set_cell_text(500, 1, "777")

    assert points[500][1] == 1000.0
    assert model.cell_text(500, 1) == "777"
    assert len(model._overrides) == 1
    result = model.to_points()
    assert result[500] == [500.0, 777.0]
    assert result[499] == points[499]


def test_editor_snapshot_detaches_metadata_but_borrows_xy_arrays():
    with tempfile.TemporaryDirectory() as root:
        library = ReferenceChartLibrary(root=root)
        points = [[0.0, 1.0], [1.0, 2.0]]
        library._series = [{
            "id": "curve", "name": "Curve", "points": points,
            "enabled": True, "kind": "xy",
        }]
        draft = library.editor_snapshot()

        assert draft[0] is not library._series[0]
        assert draft[0]["points"] is points
        draft[0]["name"] = "Draft rename"
        assert library._series[0]["name"] == "Curve"


def test_reference_dialog_route_uses_fast_editor_snapshot():
    source = (ROOT / "WinUx/ui/behaviors/plot_docking.py").read_text(encoding="utf-8")
    block = source[source.index("    def _show_reference_chart_dialog"):
                   source.index("    def _show_plot_digitizer_dialog")]
    assert "library.editor_snapshot()" in block
    assert "source_revision=revision" in block


def test_dialog_classes_are_warmed_incrementally_on_same_event_loop():
    source = (ROOT / "WinUx/view.py").read_text(encoding="utf-8")
    assert "def _prewarm_inprocess_dialog_imports" in source
    block = source[source.index("    def _prewarm_inprocess_dialog_imports"):
                   source.index("    def show_transfer_center")]
    assert "self.after(24, self._prewarm_inprocess_dialog_imports" in block
    assert "_dialog_type(names[index])" in block
    lowered = block.lower()
    assert "threading." not in lowered
    assert "multiprocessing" not in lowered
    assert "popen(" not in lowered
    assert "def _prewarm_retained_dialog_shells" in source
    retained = source[source.index("    def _prewarm_retained_dialog_shells"):
                      source.index("    def show_transfer_center")]
    assert '("settings_dialog", "SettingsDialog")' in retained
    assert '("diagnostics_dialog", "DiagnosticsDialog")' in retained
    assert "current.hide()" in retained
