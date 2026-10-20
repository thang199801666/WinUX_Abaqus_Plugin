from io import BytesIO
import json
import struct
from unittest.mock import patch
import zipfile

import pytest
from PIL import Image

from WinUx.plotdigitizer.core import DigitizerEngine, SmartDetectionResult
from WinUx.plotdigitizer.core.project_binary import MAGIC, read_pdg, write_pdg
from WinUx.plotdigitizer.application import normalize_workspace_state


def _engine(tmp_path):
    image = Image.new("RGB", (121, 121), (240, 230, 220))
    image.putpixel((40, 50), (30, 100, 220))
    source = tmp_path / "original.png"
    image.save(source)
    engine = DigitizerEngine()
    engine.load_image(str(source))
    for key, px, py, value in (("x1", 10, 110, 0), ("x2", 110, 110, 10),
                               ("y1", 10, 110, 0), ("y2", 10, 10, 100)):
        engine.set_anchor(key, px, py, value)
    engine.apply_smart_detect_result(SmartDetectionResult(
        plot_rect=(10, 10, 110, 110), curve_rgb=(30, 100, 220),
        extracted_pixels=[(index, 110 - index) for index in range(10, 111)]))
    engine.reduce_samples()
    engine.add_manual_point(40, 50)
    engine.add_dataset()
    engine.update_dataset(visible=False, locked=True)
    engine.set_active_dataset(0)
    engine.move_point("manual", 0, 45, 55)
    engine.undo()
    return engine, source


def test_pdg_contains_full_resolution_image_data_and_history_without_external_files(tmp_path):
    engine, source = _engine(tmp_path)
    path = tmp_path / "project.pdg"
    view = {"version": 1, "tool": "data", "zoom": 2, "pan": [-12, 30]}
    before = engine._snapshot()
    original_pixels = engine.image.tobytes()
    engine.save_project(str(path), view_state=view)
    assert path.read_bytes().startswith(MAGIC)
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {"project.json", "image.png"}
        payload = json.loads(archive.read("project.json"))
        assert payload["project"]["datasets"][0]["extracted_data"] == [list(point) for point in engine.active_dataset.extracted_data]
    source.unlink()
    moved = tmp_path / "moved.pdg"
    path.rename(moved)
    restored = DigitizerEngine()
    loaded_view = restored.load_project(str(moved))
    assert loaded_view == view
    assert restored._snapshot() == before
    assert restored.active_dataset.extracted_data == engine.active_dataset.extracted_data
    assert restored.image.size == (121, 121)
    assert restored.image.tobytes() == original_pixels
    assert restored.can_undo and restored.can_redo
    assert restored.redo()
    assert restored.point_pixels("manual", 0) == (45, 55)
    assert restored.undo()
    assert restored.point_pixels("manual", 0) == (40, 50)


def test_pdg_can_save_an_imageless_workspace_and_retains_view_in_headless_resave(tmp_path):
    engine = DigitizerEngine()
    view = {"version": 1, "tool": "automatic"}
    first = tmp_path / "first.pdg"
    engine.save_project(str(first), view_state=view)
    restored = DigitizerEngine()
    restored.load_project(str(first))
    assert restored.image is None
    second = tmp_path / "second.pdg"
    restored.save_project(str(second))
    document, image = read_pdg(second)
    assert image is None
    assert document["view_state"] == view


@pytest.mark.parametrize("damage", ["truncated", "version", "metadata", "image", "history", "view"])
def test_invalid_pdg_never_replaces_current_workspace_or_history(tmp_path, damage):
    engine, _source = _engine(tmp_path)
    path = tmp_path / "broken.pdg"
    engine.save_project(str(path), view_state={"version": 1, "tool": "data"})
    document, image = read_pdg(path)
    if damage == "truncated":
        path.write_bytes(path.read_bytes()[:24])
    elif damage == "version":
        data = bytearray(path.read_bytes())
        data[len(MAGIC):len(MAGIC) + 2] = struct.pack("<H", 999)
        path.write_bytes(data)
    elif damage == "history":
        document["history"]["undo"] = [["Invalid", {"not": "a state"}]]
        write_pdg(path, document, image)
    elif damage == "view":
        document["view_state"]["zoom"] = 0
        write_pdg(path, document, image)
    else:
        buffer = BytesIO()
        buffer.write(MAGIC + struct.pack("<H", 1))
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("project.json", b"not json" if damage == "metadata" else json.dumps(document))
            archive.writestr("image.png", b"not an image")
        path.write_bytes(buffer.getvalue())
    state, revision, image_before = engine._snapshot(), engine.revision, engine.image
    undo, redo = list(engine._undo_stack), list(engine._redo_stack)
    events = []
    engine.subscribe(lambda event, _: events.append(event))
    with pytest.raises((ValueError, OSError)):
        engine.load_project(str(path), view_validator=normalize_workspace_state)
    assert engine._snapshot() == state
    assert engine.image is image_before
    assert engine.revision == revision
    assert engine._undo_stack == undo and engine._redo_stack == redo
    assert events == []


def test_failed_pdg_save_preserves_existing_file_and_cleans_temporary_file(tmp_path):
    engine, _source = _engine(tmp_path)
    path = tmp_path / "existing.pdg"
    path.write_bytes(b"existing project")
    with patch("WinUx.plotdigitizer.core.project_binary.os.replace", side_effect=OSError("File in use")):
        with pytest.raises(OSError):
            engine.save_project(str(path))
    assert path.read_bytes() == b"existing project"
    assert not list(tmp_path.glob(".existing.pdg.*.tmp"))
