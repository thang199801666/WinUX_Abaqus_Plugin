from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MENU = ROOT / 'DearUIQt' / 'widgets' / 'menu.py'
JOBS = ROOT / 'WinUx' / 'ui' / 'components' / 'jobs_view.py'


def test_qmenu_does_not_reserve_a_separate_check_gutter():
    src = MENU.read_text(encoding='utf-8')
    assert 'CHECK_SLOT = 0' in src
    assert 'check_slot = 0' in src
    assert 'width=self.ICON_SLOT' in src
    assert 'pos=(check_x, 0)' in src


def test_checked_menu_action_reuses_icon_slot_instead_of_shifting_all_rows():
    src = MENU.read_text(encoding='utf-8')
    assert 'def _sync_leading_indicator' in src
    assert 'show=not checked' in src
    assert 'show=not bool(spec.get("checkable") and spec.get("checked"))' in src


def test_job_viewer_keeps_plots_checkable_without_forcing_menu_indent():
    src = JOBS.read_text(encoding='utf-8')
    assert '"id": "job_plots"' in src
    assert '"checkable": True' in src
    assert 'set_context_menu_item_checked' in src
