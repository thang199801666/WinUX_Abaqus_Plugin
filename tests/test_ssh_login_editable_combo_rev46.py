from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINUX = ROOT / "WinUx"


def _read(relative):
    return (WINUX / relative).read_text(encoding="utf-8")


def test_login_host_and_username_explicitly_request_editable_combos():
    source = _read("dialogs/login_form.py")
    assert "parent=editor_parent, editable=True" in source
    assert "combo.setEditable(True)" in source
    assert "readonly=False" in source


def test_editable_combo_editor_and_arrow_do_not_overlap():
    source = _read("components/qt_combo_box.py")
    constructor = source.split("def __init__", 1)[1].split(
        "# ------------------------------------------------------------------ API", 1)[0]
    assert "self._row = dpg.add_group(" in constructor
    assert "parent=self._row" in constructor
    assert "width=-editor_right_reserve" in constructor
    assert "self.button = dpg.add_drawlist(" in constructor
    assert "width=self.ARROW_WIDTH" in constructor
    assert "self.button = dpg.add_combo(" not in constructor
    assert "parent=self.shell,\n            width=-1,\n            pos=(0, 0)" not in constructor


def test_new_login_values_are_persisted_after_success():
    prefs = _read("preferences/login.py")
    assert 'hosts[host] = int(values["port"])' in prefs
    assert "usernames.append(username)" in prefs
    assert 'data["last_username"] = username' in prefs
