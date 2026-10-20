"""Regression coverage for the folder/file selector address dropdown."""
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def test_address_dropdown_uses_field_geometry_and_parent_window():
    source = (ROOT / 'WinUx/dialogs/folder_browser_address.py').read_text(encoding='utf-8')
    assert 'rect = self._frame.globalGeometry()' in source
    assert 'menu.popup((rect.left(), rect.bottom()))' in source
    assert 'menu._min_width = width' in source
    assert 'menu._max_width = width' in source
    assert 'parent_window=dialog.tag' in source
