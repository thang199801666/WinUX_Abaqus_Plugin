import threading

import pytest
from PIL import Image, ImageDraw

from WinUx.plotdigitizer.core import DigitizerEngine, ExtractionSettings, AxisScale
from WinUx.plotdigitizer.core.extraction import detect_curve_colors, extract_curve
from WinUx.plotdigitizer.application import SmartDetectRunner


@pytest.fixture
def chart(tmp_path):
    image = Image.new("RGB", (201, 121), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 10, 180, 110), outline="black")
    draw.line((21, 100, 179, 30), fill=(220, 30, 50), width=3)
    draw.line((21, 80, 179, 20), fill=(30, 100, 220), width=1)
    draw.line((21, 108, 179, 50), fill=(30, 180, 70), width=2)
    path = tmp_path / "chart.png"
    image.save(path)
    engine = DigitizerEngine()
    engine.load_image(str(path))
    engine.set_plot_rect((20, 10, 180, 110))
    engine.calibrate_plot_rect(0, 3.2, 0, 2000)
    return engine, path


def test_roi_normalizes_clamps_and_undo_restores_calibration(chart):
    engine, _ = chart
    assert engine.pixel_to_data(100, 60) == pytest.approx((1.6, 1000))
    assert engine.calibration.data_to_pixel(1.6, 1000) == pytest.approx((100, 60))
    engine.set_plot_rect((300, 200, -100, -50))
    assert engine.plot_rect == (0, 0, 200, 120)
    engine.calibrate_plot_rect(0, 10, 0, 100)
    assert engine.pixel_to_data(100, 60) == pytest.approx((5, 50))
    assert engine.undo()
    assert engine.pixel_to_data(100, 60) == pytest.approx((1.6, 1000))
    assert engine.undo()
    assert engine.plot_rect == (20, 10, 180, 110)
    with pytest.raises(ValueError, match="3 by 3"):
        engine.set_plot_rect((40, 40, 41, 41))
    assert engine.plot_rect == (20, 10, 180, 110)


def test_multiple_colors_and_smart_detect_preserve_picked_curve(chart):
    engine, _ = chart
    colors = detect_curve_colors(engine.image, engine.plot_roi())
    assert len(colors) == 3
    assert set(colors) == {(220, 30, 50), (30, 100, 220), (30, 180, 70)}
    engine.set_curve_color((30, 100, 220))
    assert engine.smart_detect(ExtractionSettings(smoothing=0))
    assert engine.active_dataset.curve_rgb == (30, 100, 220)
    assert engine.active_dataset.extracted_pixels[0][1] == pytest.approx(80)
    assert engine.active_dataset.extracted_pixels[-1][1] == pytest.approx(20)


def test_edit_delete_clear_undo_redo_recomputes_chart_values(chart):
    engine, _ = chart
    engine.set_curve_color((30, 100, 220))
    assert engine.extract(ExtractionSettings(smoothing=0))
    original = engine.active_dataset.to_dict()
    engine.add_manual_point(100, 60)
    engine.set_point_values("manual", 0, .8, 500)
    assert engine.point_pixels("manual", 0) == pytest.approx((60, 85))
    assert engine.undo()
    assert engine.point_pixels("manual", 0) == pytest.approx((100, 60))
    assert engine.redo()
    assert engine.active_dataset.manual_points[0].x == pytest.approx(.8)
    engine.remove_points([("auto", 0), ("auto", 1), ("manual", 0)])
    assert len(engine.active_dataset.extracted_pixels) == len(original["extracted_pixels"]) - 2
    assert not engine.active_dataset.manual_points
    assert engine.undo()
    assert engine.active_dataset.manual_points[0].y == pytest.approx(500)
    engine.clear_points()
    assert not engine.active_dataset.extracted_data
    assert engine.undo()
    assert len(engine.active_dataset.extracted_data) == len(original["extracted_pixels"])
    engine.add_manual_point(90, 50)
    assert not engine.can_redo


def test_locked_datasets_cannot_be_modified_by_edit_or_extraction(chart):
    engine, _ = chart
    engine.set_curve_color((30, 100, 220))
    engine.add_manual_point(100, 60)
    engine.update_dataset(locked=True)
    for action in (lambda: engine.add_manual_point(50, 50),
                   lambda: engine.move_point("manual", 0, 50, 50),
                   lambda: engine.remove_points([("manual", 0)]),
                   engine.clear_points, engine.extract,
                   lambda: engine.set_curve_color((20, 30, 40))):
        with pytest.raises(ValueError, match="Unlock"):
            action()
    assert engine.point_pixels("manual", 0) == (100, 60)
    engine.undo()
    assert not engine.active_dataset.locked


def test_log_point_edit_and_invalid_move_are_transactional(chart):
    engine, _ = chart
    engine.calibrate_plot_rect(1, 100, 1, 1000)
    engine.set_axis_scale(AxisScale.LOG10, AxisScale.LOG10)
    engine.add_manual_point(100, 60)
    engine.set_point_values("manual", 0, 10, 10)
    assert engine.point_pixels("manual", 0) == pytest.approx((100, 110 - 100/3))
    previous = engine.active_dataset.to_dict()
    history_count = len(engine._undo_stack)
    with pytest.raises(ValueError, match="Logarithmic"):
        engine.set_point_values("manual", 0, 0, 10)
    with pytest.raises(ValueError, match="inside the image"):
        engine.move_point("manual", 0, 500, 500)
    with pytest.raises(ValueError, match="non-negative"):
        engine.move_point("manual", -1, 50, 50)
    assert engine.active_dataset.to_dict() == previous
    assert len(engine._undo_stack) == history_count


def test_long_gaps_do_not_smooth_between_unrelated_curve_segments():
    image = Image.new("RGB", (80, 80), "white")
    draw = ImageDraw.Draw(image)
    color = (30, 100, 220)
    draw.line((0, 10, 20, 10), fill=color)
    draw.line((50, 60, 79, 60), fill=color)
    points = extract_curve(image, (0, 0, 79, 79), color,
                           ExtractionSettings(smoothing=7, max_gap_columns=5))
    assert all(y == 10 for x, y in points if x <= 20)
    assert all(y == 60 for x, y in points if x >= 50)
    assert not any(20 < x < 50 for x, y in points)


def test_async_extraction_rejects_changed_roi_before_delivery(chart):
    engine, _ = chart
    callbacks = []
    complete = threading.Event()

    def dispatch(callback):
        callbacks.append(callback)
        complete.set()

    results = []
    runner = SmartDetectRunner(engine, dispatch)
    try:
        assert runner.submit(ExtractionSettings(), 0, lambda *args: results.append(args))
        assert complete.wait(5)
        engine.set_plot_rect((30, 20, 160, 100))
        callbacks.pop()()
        assert results[0][0] is None
        assert "changed" in results[0][-1]
        assert not engine.active_dataset.extracted_pixels
    finally:
        runner.close()
