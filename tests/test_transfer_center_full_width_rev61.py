from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "transfer_center_form.py"


def test_transfer_row_outer_layout_does_not_reserve_an_unused_action_column():
    source = FORM.read_text(encoding="utf-8")
    # Outer row card is a single stretch content column (QVBoxLayout); the
    # action cell lives only inside the inner controls grid, not the card.
    block = source.split("content_layout = QVBoxLayout(parent=group_frame", 1)[1].split("controls_grid = QGridLayout(", 1)[0]
    assert "content = content_layout.tag" in block
    assert "title = QLabel(" in block
    assert "QGridLayout" not in block
    assert "action_cell" not in block
    assert "width_fixed" not in block
    assert "init_width_or_weight" not in block


def test_progress_and_cancel_use_the_full_content_width_with_only_one_fixed_action_column():
    source = FORM.read_text(encoding="utf-8")
    controls = source.split("controls_grid = QGridLayout(", 1)[1].split("stats = self.status_text", 1)[0]
    # One stretch content column plus one fixed-width action column.
    assert "column_widths=(None, self.ACTION_WIDTH)" in controls
    # Progress host fills the stretch column edge to edge.
    assert "progress_cell = controls_grid.cell(0, 0)" in controls
    assert "progress_host_frame = QFrame(" in controls
    assert "parent=progress_cell" in controls
    assert "width=-1" in controls
    assert "width=self.ACTION_WIDTH, height=self.PROGRESS_HEIGHT" in controls
