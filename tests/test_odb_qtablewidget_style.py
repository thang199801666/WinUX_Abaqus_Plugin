"""Regression contract for stable ODB native table headers."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "WinUx" / "dialogs" / "odb" / "odb_extract_form.py"


def main():
    source = FORM.read_text(encoding="utf-8")
    ast.parse(source)
    assert "class _ODBQtTable" not in source
    assert "_presentation_header_row" not in source
    assert "header_row=False" not in source
    assert 'self.history = QtTable(self.content, ("Output Variables", "Points")' in source
    assert 'self.axes[axis] = QtTable(' in source
    assert 'self.history.setColumnWidth("1", 72)' in source
    assert 'row_height=22' in source
    assert 'def _center_native_header' in source
    assert 'def _history_rows' in source
    assert "table.setAlternatingRowColors(False)" in source
    assert "table.setShowGrid(True)" in source
    print("PASS: ODB tables use stable native QtTable headers")


if __name__ == "__main__":
    main()
