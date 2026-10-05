from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "WinUx" / "dialogs" / "job_manager_form.py").read_text(encoding="utf-8")


def test_job_manager_table_fills_body_without_reserved_status_strip():
    assert "height=-1, width=-1, resizable=True" in SOURCE
    assert "height=-22" not in SOURCE


def test_job_manager_status_is_owned_by_button_box_middle_slot():
    assert "status_item=self.status" in SOURCE


def test_job_manager_mixed_controls_use_per_cell_alignment_groups():
    for token in (
        "with dpg.group() as run_cell:",
        "with dpg.group() as name_cell:",
        "with dpg.group() as version_cell:",
        "with dpg.group() as cpu_cell:",
        "with dpg.group() as precision_cell:",
        "with dpg.group() as overwrite_cell:",
        "with dpg.group() as schedule_cell:",
        "with dpg.group() as time_cell:",
    ):
        assert token in SOURCE


def test_product_version_is_unchanged():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
