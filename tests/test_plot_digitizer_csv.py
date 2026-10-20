import csv

import pytest

from WinUx.plotdigitizer.core import DigitizerEngine


def _engine():
    engine = DigitizerEngine()
    for key, px, py, value in (("x1", 0, 100, 0), ("x2", 100, 100, 10),
                               ("y1", 0, 100, 0), ("y2", 0, 0, 100)):
        engine.set_anchor(key, px, py, value)
    engine.active_dataset.extracted_pixels = [(80, 20), (20, 40)]
    engine.recompute_all_data()
    engine.add_manual_point(50, 50)
    engine.add_manual_point(20, 60)
    engine.add_dataset("Second")
    engine.add_manual_point(90, 10)
    engine.add_manual_point(10, 90)
    return engine


def _rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize("sort_by_x,expected", [(False, [8, 2, 5, 2]), (True, [2, 2, 5, 8])])
def test_csv_sorting_combines_sources_stably_without_mutating_points(tmp_path, sort_by_x, expected):
    engine = _engine()
    before, revision = engine.to_result_dict(), engine.revision
    path = tmp_path / "first.csv"
    engine.export_csv(str(path), 0, sort_by_x=sort_by_x)
    rows = _rows(path)
    assert [float(row["X"]) for row in rows] == expected
    assert [int(row["Index"]) for row in rows] == [1, 2, 3, 4]
    assert {row["Dataset"] for row in rows} == {"Serie-1"}
    if sort_by_x:
        assert [row["Source"] for row in rows[:2]] == ["Smart", "Manual"]
        assert [float(row["Y"]) for row in rows] == [60, 40, 50, 80]
        assert [float(row["PixelY"]) for row in rows] == [40, 60, 50, 20]
    assert engine.to_result_dict() == before
    assert engine.revision == revision


def test_csv_all_datasets_are_sorted_independently(tmp_path):
    engine = _engine()
    path = tmp_path / "all.csv"
    engine.export_csv(str(path), sort_by_x=True)
    rows = _rows(path)
    assert [row["Dataset"] for row in rows] == ["Serie-1"] * 4 + ["Second"] * 2
    assert [float(row["X"]) for row in rows] == [2, 2, 5, 8, 1, 9]
    assert [int(row["Index"]) for row in rows] == [1, 2, 3, 4, 1, 2]


def test_empty_active_dataset_cannot_export_other_datasets(tmp_path):
    engine = _engine()
    empty = engine.add_dataset("Empty")
    path = tmp_path / "empty.csv"
    with pytest.raises(ValueError, match="Extract a curve"):
        engine.export_csv(str(path), empty)
    assert not path.exists()


@pytest.mark.parametrize("index", [-1, 2, True, 0.5])
def test_invalid_export_index_preserves_existing_file(tmp_path, index):
    engine = _engine()
    path = tmp_path / "existing.csv"
    path.write_text("existing data", encoding="utf-8")
    with pytest.raises(IndexError):
        engine.export_csv(str(path), index)
    assert path.read_text(encoding="utf-8") == "existing data"
