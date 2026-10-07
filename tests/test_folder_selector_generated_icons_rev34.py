from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = ROOT / "WinUx" / "dialogs" / "folder_browser_style.py"
ICON_DIR = ROOT / "WinUx" / "Resources" / "folder_selector_icons"

EXPECTED_FILES = {
    "back.png",
    "forward.png",
    "up.png",
    "refresh.png",
    "search.png",
    "new_folder.png",
    "details.png",
    "list.png",
    "drive.png",
    "chevron.png",
}


def test_generated_folder_selector_assets_exist():
    present = {path.name for path in ICON_DIR.glob("*.png")}
    assert EXPECTED_FILES.issubset(present)


def test_folder_browser_style_uses_generated_toolbar_icons():
    source = STYLE.read_text(encoding="utf-8")
    assert 'FOLDER_SELECTOR_ICON_DIR' in source
    assert 'FOLDER_SELECTOR_ICON_MAP' in source
    assert 'FOLDER_SELECTOR_MASTER_SIZE = 64' in source
    assert 'def _generated_folder_selector_icon' in source
    assert '"back": "back.png"' in source
    assert '"forward": "forward.png"' in source
    assert '"up": "up.png"' in source
    assert '"refresh": "refresh.png"' in source
    assert '"search": "search.png"' in source
    assert '"new_folder": "new_folder.png"' in source
    assert '"drive": "drive.png"' in source
    assert '"edit_address": "chevron.png"' in source
    assert 'generated = _generated_folder_selector_icon(key, disabled=disabled, size=20)' in source
    assert 'key = "list" if str(mode or "details").strip().lower() == "list" else "details"' in source
