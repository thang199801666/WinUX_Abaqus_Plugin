import pytest

from WinUx.plotdigitizer.core import DigitizerEngine, ExtractionSettings


def test_duplicate_locked_dataset_is_independent_editable_and_undoable():
    engine = DigitizerEngine()
    engine.set_curve_color((220, 30, 50))
    engine.set_settings(ExtractionSettings(smoothing=0, stride=2))
    engine.add_manual_point(20, 30)
    engine.active_dataset.extracted_pixels = [(10, 40)]
    engine.update_dataset(locked=True)
    original = engine.active_dataset.to_dict()
    index = engine.duplicate_dataset()
    assert index == 1
    duplicate = engine.active_dataset
    assert duplicate.name == "Serie-1 (copy)"
    assert not duplicate.locked
    assert duplicate.marker_style != engine.datasets[0].marker_style
    assert duplicate.settings == engine.datasets[0].settings
    assert duplicate.settings is not engine.datasets[0].settings
    assert duplicate.manual_points[0] is not engine.datasets[0].manual_points[0]
    assert duplicate.extracted_pixels is not engine.datasets[0].extracted_pixels
    assert engine.undo()
    assert len(engine.datasets) == 1
    assert engine.active_dataset.to_dict() == original
    assert engine.redo()
    assert engine.active_dataset_index == 1
    engine.move_point("manual", 0, 25, 35)
    engine.move_point("auto", 0, 15, 45)
    assert engine.datasets[0].to_dict() == original


def test_duplicate_names_are_unique_case_insensitively():
    engine = DigitizerEngine()
    engine.add_dataset("SERIE-1 (COPY)")
    engine.duplicate_dataset(0)
    assert engine.active_dataset.name == "Serie-1 (copy 2)"
    engine.duplicate_dataset(0)
    assert engine.active_dataset.name == "Serie-1 (copy 3)"


@pytest.mark.parametrize("active,removed,expected", [(1, 0, "B"), (2, 0, "C"), (0, 2, "A"),
                                                       (1, 1, "C"), (2, 2, "B")])
def test_delete_dataset_preserves_active_identity_or_selects_neighbor(active, removed, expected):
    engine = DigitizerEngine()
    engine.update_dataset(name="A")
    engine.add_dataset("B")
    engine.add_dataset("C")
    engine.set_active_dataset(active)
    engine.remove_dataset(removed)
    assert engine.active_dataset.name == expected
    assert engine.undo()
    assert engine.active_dataset_index == active
    assert [ds.name for ds in engine.datasets] == ["A", "B", "C"]


@pytest.mark.parametrize("index", [-1, 2, True, 0.5])
def test_invalid_dataset_index_cannot_mutate_state(index):
    engine = DigitizerEngine()
    engine.add_dataset()
    before = engine.to_result_dict()
    revision = engine.revision
    for operation in (engine.duplicate_dataset, engine.remove_dataset, engine.set_active_dataset,
                      lambda value: engine.update_dataset(visible=False, dataset_index=value)):
        with pytest.raises(IndexError):
            operation(index)
        assert engine.to_result_dict() == before
        assert engine.revision == revision


def test_default_series_names_are_sequential_and_case_insensitive():
    engine = DigitizerEngine()
    engine.add_dataset()
    engine.add_dataset()
    assert [dataset.name for dataset in engine.datasets] == ["Serie-1", "Serie-2", "Serie-3"]
    engine.update_dataset(name="sErIe-4")
    engine.add_dataset()
    assert engine.active_dataset.name == "Serie-5"


def test_indexed_visibility_and_lock_do_not_change_the_active_series_and_are_undoable():
    engine = DigitizerEngine()
    engine.add_dataset()
    engine.set_active_dataset(0)
    engine.update_dataset(visible=False, locked=True, dataset_index=1)
    assert engine.active_dataset_index == 0
    assert engine.datasets[0].visible and not engine.datasets[0].locked
    assert not engine.datasets[1].visible and engine.datasets[1].locked
    assert engine.undo()
    assert engine.datasets[1].visible and not engine.datasets[1].locked
    assert engine.redo()
    assert not engine.datasets[1].visible and engine.datasets[1].locked
