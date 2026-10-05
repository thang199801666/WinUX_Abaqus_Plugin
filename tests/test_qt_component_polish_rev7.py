from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def read(rel):
    return (WINUX / rel).read_text(encoding="utf-8")


def test_pushbuttons_have_stable_qt_height():
    src = read("widgets/controls.py")
    assert 'options["height"] = METRICS.button_height if height is None else int(height)' in src


def test_checkbox_indicator_is_compact_and_splitter_is_subtle():
    src = read("widgets/imgui_qt_style.py")
    assert "check_size: int = 14" in src
    assert "mvStyleVar_FramePadding, 0, 0" in src
    assert "line = p.FOCUS if active else p.BORDER_LIGHT" in src


def test_login_form_uses_tighter_qformlayout_geometry():
    src = read("dialogs/login_form.py")
    assert 'self.preferred_size = (420, 184)' in src
    assert 'label_width=78' in src
    host = read("dialogs/login_dialog.py")
    assert 'width=420, height=226' in host


def test_job_viewer_header_follows_qheaderview_alignment():
    theme = read("components/explorer_themes.py")
    jobs = read("components/jobs_view.py")
    block = theme.split('"Job Viewer": {', 1)[1].split('"WinSCP": {', 1)[0]
    assert '"header_alignment": "column"' in block
    assert '"sort_indicator_mode": "edge"' in block
    assert 'set_metrics(row_height=23, header_height=26, cell_padding=6)' in jobs


def test_product_version_stays_110():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "1.1.0"
