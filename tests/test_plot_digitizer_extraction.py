import csv
import threading

import pytest
from PIL import Image, ImageDraw

from WinUx.plotdigitizer.application import SmartDetectRunner
from WinUx.plotdigitizer.core import AxisScale, DigitizerEngine, ExtractionSettings


def _chart(tmp_path):
    image = Image.new("RGB", (121, 121), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 110, 110), outline="black")
    draw.line((10, 100, 110, 20), fill=(220, 30, 50), width=1)
    path = tmp_path / "chart.png"
    image.save(path)
    engine = DigitizerEngine()
    engine.load_image(str(path))
    return engine, path


def _calibrate(engine):
    for key, px, py, value in (
        ("x1", 10, 110, 0), ("x2", 110, 110, 10),
        ("y1", 10, 110, 0), ("y2", 10, 10, 100),
    ):
        engine.set_anchor(key, px, py, value)


def test_thin_curve_image_to_calibrated_csv_and_project(tmp_path):
    engine, _ = _chart(tmp_path)
    _calibrate(engine)
    assert engine.sample_curve_color(60, 60) == (220, 30, 50)
    assert engine.extract(ExtractionSettings(smoothing=0))
    points = engine.active_dataset.extracted_data
    assert len(points) == 101
    assert points[0] == pytest.approx((0, 10))
    assert points[50] == pytest.approx((5, 50))
    assert points[-1] == pytest.approx((10, 90))
    output = tmp_path / "chart.csv"
    engine.export_csv(str(output))
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 101
    assert float(rows[50]["X"]) == pytest.approx(5)
    assert float(rows[50]["Y"]) == pytest.approx(50)
    project = tmp_path / "chart.json"
    engine.save_project(str(project))
    restored = DigitizerEngine()
    restored.load_project(str(project))
    assert restored.active_dataset.extracted_data == points


def test_smart_detection_can_be_calibrated_after_extraction(tmp_path):
    engine, _ = _chart(tmp_path)
    assert engine.smart_detect(ExtractionSettings(smoothing=0))
    assert engine.active_dataset.extracted_pixels
    assert not engine.active_dataset.extracted_data
    with pytest.raises(ValueError, match="calibration"):
        engine.export_csv(str(tmp_path / "not_ready.csv"))
    assert not (tmp_path / "not_ready.csv").exists()
    _calibrate(engine)
    assert len(engine.active_dataset.extracted_data) == len(engine.active_dataset.extracted_pixels)
    engine.set_anchor("x2", 110, 110, 20)
    assert engine.pixel_to_data(60, 60) == pytest.approx((10, 50))


def test_loading_another_image_resets_image_specific_state(tmp_path):
    engine, path = _chart(tmp_path)
    _calibrate(engine)
    engine.sample_curve_color(60, 60)
    engine.extract()
    engine.load_image(str(path))
    assert not engine.calibration_ready()
    assert not engine.active_dataset.extracted_pixels
    assert engine.active_dataset.curve_rgb is None


@pytest.mark.parametrize("px,value", [(10, 10), (110, 0), (110, float("nan"))])
def test_invalid_anchor_edit_preserves_previous_calibration(tmp_path, px, value):
    engine, _ = _chart(tmp_path)
    _calibrate(engine)
    previous = engine.calibration.to_dict()
    with pytest.raises(ValueError):
        engine.set_anchor("x2", px, 110, value)
    assert engine.calibration.to_dict() == previous
    assert engine.calibration_ready()


def test_logarithmic_scale_validation_and_mapping(tmp_path):
    engine, _ = _chart(tmp_path)
    _calibrate(engine)
    with pytest.raises(ValueError, match="Logarithmic"):
        engine.set_axis_scale(AxisScale.LOG10)
    assert engine.calibration.scale_x == AxisScale.LINEAR
    engine.set_anchor("x1", 10, 110, 1)
    engine.set_anchor("x2", 110, 110, 100)
    engine.set_axis_scale(AxisScale.LOG10)
    assert engine.pixel_to_data(60, 60) == pytest.approx((10, 50))


def test_worker_result_is_discarded_when_image_changes_before_delivery(tmp_path):
    engine, path = _chart(tmp_path)
    queued = []
    completed = threading.Event()

    def dispatch(callback):
        queued.append(callback)
        completed.set()

    results = []
    runner = SmartDetectRunner(engine, dispatch)
    try:
        assert runner.submit(ExtractionSettings(), 0, lambda *args: results.append(args))
        assert completed.wait(10)
        assert runner.busy
        assert not runner.submit(ExtractionSettings(), 0, lambda *args: None)
        engine.load_image(str(path))
        queued.pop()()
        assert not runner.busy
        assert results[0][0] is None
        assert "changed" in results[0][-1]
        assert not engine.active_dataset.extracted_pixels
    finally:
        runner.close()


def test_datasets_receive_distinct_marker_styles_and_preserve_them_in_projects(tmp_path):
    engine, _ = _chart(tmp_path)
    assert engine.datasets[0].marker_style == "circle"
    engine.add_dataset("Curve 2")
    engine.add_dataset("Curve 3")
    assert [ds.marker_style for ds in engine.datasets[:3]] == ["circle", "square", "triangle"]

    project = tmp_path / "markers.json"
    engine.save_project(str(project))
    restored = DigitizerEngine()
    restored.load_project(str(project))
    assert [ds.marker_style for ds in restored.datasets[:3]] == ["circle", "square", "triangle"]


def test_loading_legacy_project_assigns_marker_styles_when_missing(tmp_path):
    project = tmp_path / "legacy.json"
    project.write_text(
        '{\n'
        '  "version": 2,\n'
        '  "image_path": null,\n'
        '  "plot_rect": null,\n'
        '  "calibration": {},\n'
        '  "active_dataset_index": 0,\n'
        '  "datasets": [\n'
        '    {"name": "A", "visible": true, "locked": false, "curve_rgb": null, "extracted_pixels": [], "manual_points": [], "settings": {}},\n'
        '    {"name": "B", "visible": true, "locked": false, "curve_rgb": null, "extracted_pixels": [], "manual_points": [], "settings": {}}\n'
        '  ]\n'
        '}\n',
        encoding="utf-8",
    )
    engine = DigitizerEngine()
    engine.load_project(str(project))
    assert [ds.marker_style for ds in engine.datasets[:2]] == ["circle", "square"]
