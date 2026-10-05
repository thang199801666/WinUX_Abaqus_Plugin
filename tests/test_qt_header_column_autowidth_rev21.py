from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COL = (ROOT / 'WinUx/components/explorer_columns.py').read_text(encoding='utf-8')
LAY = (ROOT / 'WinUx/components/explorer_layout.py').read_text(encoding='utf-8')
PTR = (ROOT / 'WinUx/components/explorer_pointer_dispatch.py').read_text(encoding='utf-8')


def test_auto_width_has_single_live_viewport_sync_entrypoint():
    assert 'def _sync_auto_width_to_viewport' in COL
    assert 'self._fit_columns_auto_width(available, locked_key=locked_key)' in COL
    assert 'self._last_available_width = available' in COL


def test_auto_width_syncs_after_listview_resize_next_frame():
    assert 'def _sync_after_resize' in LAY
    assert 'self._sync_auto_width_to_viewport(layout=True)' in LAY
    assert 'dpg.get_frame_count() + 1' in LAY


def test_auto_width_syncs_on_startup_after_real_viewport_measurement():
    marker = 'if self.auto_width_enabled:\n                            self._sync_auto_width_to_viewport()'
    assert marker in LAY


def test_header_resize_rebalances_other_columns_immediately():
    assert 'self._sync_auto_width_to_viewport(locked_key=self._resize_key)' in PTR
