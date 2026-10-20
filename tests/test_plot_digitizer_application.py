from WinUx.plotdigitizer.application import dataset_xy_points, reference_candidate, unique_series_name
from WinUx.plotdigitizer.core.models import DataPoint, Dataset


def test_reference_candidate_combines_extracted_and_manual_points():
    dataset = Dataset(name="Curve")
    dataset.extracted_data = [(1.0, 2.0), (2.0, 4.0)]
    dataset.manual_points = [DataPoint(10, 20, x=3.0, y=6.0)]
    assert dataset_xy_points(dataset) == [[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]]
    item = reference_candidate(dataset, ["Curve"])
    assert item["name"] == "Curve (2)"
    assert item["kind"] == "xy"


def test_unique_reference_name_is_case_insensitive():
    assert unique_series_name("Curve", ["curve", "Curve (2)"]) == "Curve (3)"
