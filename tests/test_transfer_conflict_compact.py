"""Compact transfer-conflict dialog presentation helpers."""
import stat
from types import SimpleNamespace

from WinUx.dialogs.transfer_conflict_form import TransferConflictDialog
from DearUIQt.gui.style import METRICS


def _state(size, mode):
    return SimpleNamespace(size=size, regular=stat.S_ISREG(mode), kind='directory')


def test_human_readable_conflict_sizes():
    regular = stat.S_IFREG | 0o644
    assert TransferConflictDialog._size(_state(0, regular)) == '0 B'
    assert TransferConflictDialog._size(_state(1024, regular)) == '1.00 KB'
    assert TransferConflictDialog._size(_state(849_861_704, regular)) == '810 MB'
    assert TransferConflictDialog._size(None) == 'Missing'


def test_compact_action_labels_keep_backend_policies():
    assert TransferConflictDialog.ACTIONS['Skip'] == 'skip'
    assert TransferConflictDialog.ACTIONS['Replace'] == 'replace'
    assert TransferConflictDialog.ACTIONS['Newer only'] == 'newer'
    assert TransferConflictDialog.ACTIONS['Rename file'] == 'rename'
    assert TransferConflictDialog.ACTION_LABELS['rename'] == 'Rename'


def test_conflict_table_height_tracks_rows_and_stays_bounded():
    row_height = METRICS.control_height + 2
    assert TransferConflictDialog._table_height(0) == 26 + row_height
    assert TransferConflictDialog._table_height(1) == 26 + row_height
    assert TransferConflictDialog._table_height(3) == 26 + 3 * row_height
    assert TransferConflictDialog._table_height(200) == 26 + 6 * row_height
