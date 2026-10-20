from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "WinUx/ui/components/reference_data_table.py"
FORM = ROOT / "WinUx/dialogs/reference_chart_form.py"


def test_reference_worksheet_uses_row_number_gutter_for_excel_selection():
    source = TABLE.read_text(encoding="utf-8")
    assert "def _row_header_at_pointer" in source
    assert "def select_row(self, row, *, ctrl=False, shift=False)" in source
    assert "QKeyboard.isControlDown" in source
    assert "QKeyboard.isShiftDown" in source
    assert "highlight_table_row" in source
    assert "unhighlight_table_row" in source


def test_reference_ctrl_c_copies_only_selected_rows():
    source = TABLE.read_text(encoding="utf-8")
    key_block = source[source.index("    def _key_pressed"):source.index("    def focus_cell")]
    copy_block = source[source.index("    def copy_selected_rows"):source.index("    # ------------------------------------------------------------------\n    # Pointer hit testing")]
    assert "self.copy_selected_rows()" in key_block
    assert "sorted(self._selected_rows)" in copy_block
    assert '"\\t".join' in copy_block
    assert '"\\n".join' in copy_block
    assert "model.clipboard_text()" not in copy_block


def test_reference_footer_requires_selection_before_copy():
    source = FORM.read_text(encoding="utf-8")
    assert '("Copy Selected", self._copy_table, "secondary", False)' in source
    assert "if not self.data_table.copy_selected_rows():" in source
    assert "selected row" in source


class _Model:
    row_count = 8

    def row_text(self, row):
        return [str(row), str(row * 10)]


class _Clipboard:
    def __init__(self):
        self.value = None

    def setText(self, value):
        self.value = str(value)


def _logic_sheet():
    from WinUx.ui.components.reference_data_table import ReferenceDataTable
    sheet = object.__new__(ReferenceDataTable)
    sheet.model = _Model()
    sheet._selected_rows = set()
    sheet._selection_anchor = None
    sheet._closed = False
    sheet._commit_active_editor = lambda: None
    sheet._read_inputs = lambda: None
    sheet._clipboard = _Clipboard()
    sheet.on_error = lambda message: setattr(sheet, "last_error", message)
    sheet._set_row_highlight = lambda row, selected: True
    return sheet


def test_row_selection_supports_plain_ctrl_and_shift_like_excel():
    sheet = _logic_sheet()
    assert sheet.select_row(2)
    assert sheet.selected_rows == (2,)
    assert sheet.select_row(5, ctrl=True)
    assert sheet.selected_rows == (2, 5)
    assert sheet.select_row(7, shift=True)
    assert sheet.selected_rows == (5, 6, 7)
    assert sheet.select_row(6, ctrl=True)
    assert sheet.selected_rows == (5, 7)


def test_copy_selected_rows_emits_excel_tsv_without_unselected_rows():
    sheet = _logic_sheet()
    sheet._selected_rows = {1, 3, 4}
    assert sheet.copy_selected_rows() is True
    assert sheet._clipboard.value == "1\t10\n3\t30\n4\t40"


def test_copy_requires_at_least_one_selected_row():
    sheet = _logic_sheet()
    assert sheet.copy_selected_rows() is False
    assert "Select one or more rows" in sheet.last_error
