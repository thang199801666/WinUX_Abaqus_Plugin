from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "plotdigitizer" / "ui" / "dialog.py"


def test_plot_digitizer_uses_sectioned_workflow_and_prominent_primary_actions():
    source = FORM.read_text(encoding="utf-8")
    assert 'with self.section("Workflow", parent=panel) as group:' in source
    assert 'with self.section("Manual Extraction", parent=manual_page) as panel:' in source
    assert 'with self.section("View Data", parent=panel) as group:' in source
    assert 'role="primary", parent=panel, width=-1)' in source  # calibrate/apply controls remain prominent
    assert 'role="primary", parent=self.manual_commands.cell(0, 0), width=-1)' in source
