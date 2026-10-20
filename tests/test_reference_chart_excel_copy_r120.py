from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "WinUx/ui/components/reference_data_table.py"
FORM = ROOT / "WinUx/dialogs/reference_chart_form.py"


def test_reference_xy_sheet_drops_navigation_toolbar_chrome():
    source = TABLE.read_text(encoding="utf-8")
    assert 'QPushButton("First"' not in source
    assert 'QPushButton("Prev"' not in source
    assert 'QPushButton("Next"' not in source
    assert 'QPushButton("Last"' not in source
    assert 'QLabel("", parent=self.controls)' not in source
    assert 'class _PassiveNavigationControl' in source


def test_reference_xy_sheet_supports_ctrl_c_full_table_copy():
    source = TABLE.read_text(encoding="utf-8")
    block = source[source.index('    def _key_pressed'):source.index('    def focus_cell')]
    assert 'Qt.Key_C' in block
    assert 'self.copy_selected_rows()' in block


def test_reference_chart_footer_exposes_copy_table_action():
    source = FORM.read_text(encoding="utf-8")
    assert '("Copy Selected", self._copy_table, "secondary", False)' in source
    assert 'Paste directly into Excel.' in source
