import json
import shutil

import pytest
from PIL import Image

from WinUx.plotdigitizer.core import DigitizerEngine


def _project(tmp_path):
    folder = tmp_path / "original"
    folder.mkdir()
    image_path = folder / "chart.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    engine = DigitizerEngine()
    engine.load_image(str(image_path))
    for key, px, py, value in (
        ("x1", 10, 90, 0), ("x2", 90, 90, 10),
        ("y1", 10, 90, 0), ("y2", 10, 10, 100),
    ):
        engine.set_anchor(key, px, py, value)
    engine.add_manual_point(50, 50)
    path = folder / "project.json"
    engine.save_project(str(path))
    return engine, path


@pytest.mark.parametrize("invalid", ["version", "calibration", "point", "settings", "fractional_settings", "segment_boundaries", "missing_image"])
def test_failed_project_load_preserves_image_data_history_and_notifications(tmp_path, invalid):
    engine, path = _project(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if invalid == "version":
        data["version"] = 999
    elif invalid == "calibration":
        data["calibration"]["x2"]["px"] = data["calibration"]["x1"]["px"]
    elif invalid == "point":
        data["datasets"][0]["manual_points"][0]["px"] = 1000
    elif invalid == "settings":
        data["datasets"][0]["settings"]["stride"] = 0
    elif invalid == "fractional_settings":
        data["datasets"][0]["settings"]["smoothing"] = 1.5
    elif invalid == "segment_boundaries":
        data["datasets"][0]["extracted_breaks"] = [1]
    else:
        data["image_path"] = str(tmp_path / "missing.png")
        data.pop("image_path_relative")
    path.write_text(json.dumps(data), encoding="utf-8")
    before = engine.to_result_dict()
    image, revision = engine.image, engine.revision
    events = []
    engine.subscribe(lambda event, _: events.append(event))
    with pytest.raises((ValueError, OSError)):
        engine.load_project(str(path))
    assert engine.to_result_dict() == before
    assert engine.image is image
    assert engine.revision == revision
    assert events == []
    assert engine.undo()
    assert not engine.active_dataset.manual_points
    assert engine.redo()
    assert engine.to_result_dict() == before


def test_project_and_image_can_be_moved_together(tmp_path):
    original, path = _project(tmp_path)
    moved = tmp_path / "moved"
    shutil.move(str(path.parent), str(moved))
    restored = DigitizerEngine()
    events = []
    restored.subscribe(lambda event, _: events.append(event))
    restored.load_project(str(moved / path.name))
    assert restored.image_path == str((moved / "chart.png").resolve())
    assert restored.active_dataset.manual_points == original.active_dataset.manual_points
    assert restored.calibration.to_dict() == original.calibration.to_dict()
    assert events == ["project_loaded"]
    assert not restored.can_undo


def test_legacy_relative_image_path_is_resolved_against_project(tmp_path):
    _, path = _project(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("image_path_relative")
    data["image_path"] = "chart.png"
    path.write_text(json.dumps(data), encoding="utf-8")
    restored = DigitizerEngine()
    restored.load_project(str(path))
    assert restored.image_path == str((path.parent / "chart.png").resolve())


def test_imageless_project_clears_old_image_and_clamps_legacy_active_index(tmp_path):
    engine, _ = _project(tmp_path)
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"version": 2, "active_dataset_index": -1,
                                "datasets": [{"name": "A"}, {"name": "B"}]}), encoding="utf-8")
    engine.load_project(str(path))
    assert engine.image is None
    assert engine.image_path is None
    assert engine.active_dataset_index == 0
    assert engine.active_dataset.name == "A"
    assert not engine.can_undo
