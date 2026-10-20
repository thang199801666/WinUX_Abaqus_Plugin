import math

import pytest

from WinUx.plotdigitizer.core import AxisScale, DigitizerEngine, SmartDetectionResult
from WinUx.plotdigitizer.core.reduction import simplify_indices


def _check_error(points, retained, tolerance):
    assert retained == sorted(set(retained))
    assert retained[0] == 0 and retained[-1] == len(points) - 1
    for first, last in zip(retained, retained[1:]):
        ax, ay = points[first]
        bx, by = points[last]
        dx, dy = bx - ax, by - ay
        denominator = dx * dx + dy * dy
        for px, py in points[first:last + 1]:
            if not denominator:
                distance = math.hypot(px - ax, py - ay)
            else:
                fraction = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / denominator))
                distance = math.hypot(px - ax - fraction * dx, py - ay - fraction * dy)
            assert distance <= tolerance + 1e-9


def _set_auto(engine, points):
    assert engine.apply_smart_detect_result(SmartDetectionResult(
        curve_rgb=(30, 100, 220), extracted_pixels=points))


def test_exact_straight_samples_reduce_to_original_endpoints():
    points = [(index, 2 * index + 1) for index in range(100)]
    assert simplify_indices(points, 0) == [0, 99]
    assert simplify_indices([]) == []
    assert simplify_indices([(1, 2)]) == [0]


def test_curve_reduction_is_bounded_and_does_not_create_or_reorder_samples():
    points = [(index, 50 + 15 * math.sin(index / 12) + 0.08 * math.sin(index * 3))
              for index in range(121)]
    retained = simplify_indices(points, 0.5)
    assert 5 < len(retained) < 40
    _check_error(points, retained, 0.5)


def test_peaks_vertical_edges_backtracking_and_closed_loops_are_preserved():
    points = [(0, 0), (1, 0), (2, 0), (2, 2), (2, 4), (3, 4), (4, 4)]
    assert simplify_indices(points, 0.1) == [0, 2, 4, 6]
    assert simplify_indices([(0, 0), (10, 0), (5, 0)], 0.5) == [0, 1, 2]
    assert simplify_indices([(0, 0), (3, 0), (1, 0), (4, 0)], 0.5) == [0, 1, 2, 3]
    assert simplify_indices([(0, 0), (3, 0), (3, 0), (1, 0), (1, 0), (4, 0)], 0.5) == [0, 1, 3, 5]
    loop = [(0, 0), (5, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    assert simplify_indices(loop, 0.5) == [0, 2, 3, 4, 5]


def test_many_sharp_corners_do_not_exceed_python_recursion_limit():
    points = [(index, 5 * (index % 2)) for index in range(1300)]
    assert simplify_indices(points, 0) == list(range(1300))


def test_engine_reduction_keeps_sources_separate_and_is_one_undoable_edit():
    engine = DigitizerEngine()
    _set_auto(engine, [(index, 2 * index) for index in range(21)])
    for index in range(11):
        engine.add_manual_point(index, 100)
    before = engine.active_dataset.to_dict()
    revision, history = engine.revision, len(engine._undo_stack)
    assert engine.reduce_samples(0) == 28
    assert engine.active_dataset.extracted_pixels == [(0, 0), (20, 40)]
    assert [(point.px, point.py) for point in engine.active_dataset.manual_points] == [(0, 100), (10, 100)]
    assert engine.revision == revision + 1
    assert len(engine._undo_stack) == history + 1
    assert engine.undo()
    assert engine.active_dataset.to_dict() == before
    assert engine.redo()
    assert len(engine.active_dataset.extracted_pixels) == 2
    revision = engine.revision
    assert engine.reduce_samples(0) == 0
    assert engine.revision == revision


def test_known_segments_survive_reduction_project_reload_and_point_deletion(tmp_path):
    engine = DigitizerEngine()
    _set_auto(engine, [(index, 0) for index in range(11)] + [(index, 0) for index in range(100, 111)])
    assert engine.reduce_samples() == 18
    assert engine.active_dataset.extracted_pixels == [(0, 0), (10, 0), (100, 0), (110, 0)]
    assert engine.active_dataset.extracted_breaks == [2]
    assert engine.reduce_samples(10) == 0
    project = tmp_path / "gaps.json"
    engine.save_project(str(project))
    restored = DigitizerEngine()
    restored.load_project(str(project))
    assert restored.active_dataset.extracted_breaks == [2]
    restored.remove_points([("auto", 0)])
    assert restored.active_dataset.extracted_breaks == [1]
    assert restored.reduce_samples(10) == 0
    assert restored.undo()
    assert restored.active_dataset.extracted_breaks == [2]
    restored.remove_points([("auto", 0), ("auto", 1)])
    assert restored.active_dataset.extracted_breaks == []


def test_higher_tolerance_does_not_treat_reduced_spacing_as_an_extraction_gap():
    engine = DigitizerEngine()
    points = [(index, 0.75 * (1 - abs(index - 50) / 50)) for index in range(101)]
    _set_auto(engine, points)
    assert engine.reduce_samples(0.5) == 98
    assert engine.active_dataset.extracted_breaks == []
    assert engine.reduce_samples(1) == 1
    assert engine.active_dataset.extracted_pixels == [points[0], points[-1]]


def test_logarithmic_calibration_also_preserves_numeric_xy_curvature():
    engine = DigitizerEngine()
    for key, px, py, value in (("x1", 0, 100, 1), ("x2", 100, 100, 100),
                               ("y1", 0, 100, 0), ("y2", 0, 0, 100)):
        engine.set_anchor(key, px, py, value)
    engine.set_axis_scale(x=AxisScale.LOG10)
    pixels = [(index, 100 - index) for index in range(101)]
    _set_auto(engine, pixels)
    original = list(engine.active_dataset.extracted_data)
    removed = engine.reduce_samples(0.5)
    assert 0 < removed < 99  # Two endpoints would incorrectly make the XY curve straight.
    retained = [int(px) for px, _py in engine.active_dataset.extracted_pixels]
    geometry = [((x - 1) / 99 * 100, y) for x, y in original]
    _check_error(geometry, retained, 0.5)
    assert engine.active_dataset.extracted_data == [original[index] for index in retained]


@pytest.mark.parametrize("error", [-1, float("nan"), float("inf"), True, "invalid"])
def test_invalid_reduction_error_is_transactional(error):
    engine = DigitizerEngine()
    _set_auto(engine, [(index, index) for index in range(10)])
    before = engine.active_dataset.to_dict()
    revision = engine.revision
    with pytest.raises(ValueError):
        engine.reduce_samples(error)
    assert engine.active_dataset.to_dict() == before
    assert engine.revision == revision


def test_locked_dataset_cannot_be_reduced():
    engine = DigitizerEngine()
    _set_auto(engine, [(index, index) for index in range(10)])
    engine.update_dataset(locked=True)
    before = engine.active_dataset.to_dict()
    with pytest.raises(ValueError, match="Unlock"):
        engine.reduce_samples()
    assert engine.active_dataset.to_dict() == before
