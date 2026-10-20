from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "job_schedule_form.py"


def test_job_schedule_rows_use_compact_qt_layout_lanes_for_vertical_centering():
    source = FORM.read_text(encoding="utf-8")
    assert 'METRICS, aligned_cell_theme, compact_stack_theme' in source
    assert 'TEXT_TOP_PAD = (METRICS.control_height - METRICS.check_size) // 2' in source
    assert 'def text_cell(column, value):' in source
    assert 'holder_layout = QVBoxLayout(' in source
    assert 'aligned_cell_theme()' in source
    assert 'QSpacer(0, self.TEXT_TOP_PAD, parent=holder_layout' in source
    assert 'QLabel(str(value), parent=holder_layout' in source


def test_job_schedule_command_cell_uses_same_vertical_lane_strategy():
    source = FORM.read_text(encoding="utf-8")
    assert 'command_layout = QVBoxLayout(parent=native_row' in source
    assert 'aligned_cell_theme()' in source
    assert 'lane_layout = QHBoxLayout(' in source
    assert 'compact_stack_theme()' in source
    assert 'QPushButton(' in source
