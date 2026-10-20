from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx/dialogs/reference_chart_form.py"
TABLE = ROOT / "WinUx/ui/components/reference_data_table.py"


def test_reference_chart_compact_header_rows_do_not_consume_editor_height():
    source = FORM.read_text(encoding="utf-8")
    type_block = source[source.index("self._type_grid = self.own_widget(QGridLayout("):
                        source.index("QLabel(\"Reference type\"")]
    name_block = source[source.index("self._name_grid = self.own_widget(QGridLayout("):
                        source.index("QLabel(\"Series name\"")]

    assert "height=32" in type_block
    assert "height=-1" not in type_block
    assert "height=32" in name_block
    assert "height=-1" not in name_block


def test_reference_chart_xy_worksheet_remains_the_vertical_expanding_child():
    source = FORM.read_text(encoding="utf-8")
    table_block = source[source.index("self.data_table = ReferenceDataTable("):
                         source.index("self._clipboard = QClipboard()")]
    assert "height=-1" in table_block


def test_reference_chart_first_geometry_pass_only_kicks_deferred_population():
    form = FORM.read_text(encoding="utf-8")
    table = TABLE.read_text(encoding="utf-8")
    init_tail = form[form.index("self.view.after(1, self._sync_pane_geometry)"):
                     form.index("    def layout_dialog")]
    assert "self.data_table.refresh_visible_page" in init_tail
    refresh = table[table.index("    def refresh_visible_page"):
                    table.index("    def has_data")]
    assert "self._extend_population_target()" in refresh
    assert "_ensure_native_row(" not in refresh
    assert "to_points(" not in refresh
    assert "clipboard_text(" not in refresh
