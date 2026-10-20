"""Portable regression coverage for Plot Digitizer preferences.

The production canvas is Windows-native; persistence, validation, marker
hit-testing and view-update dispatch are tested without a DPG viewport.
"""
import json
from types import SimpleNamespace

from WinUx.preferences.plot_digitizer import PlotDigitizerPreferences
from WinUx.plotdigitizer.application.workspace_state import normalize_workspace_state
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.plotdigitizer.ui.markers import cursor_hits_marker, marker_metrics


def test_preferences_load_defaults_and_survive_reinstantiation(tmp_path):
    prefs = PlotDigitizerPreferences(root=tmp_path)
    defaults = dict(PlotDigitizerPreferences.DEFAULTS)
    assert prefs.load() == defaults
    changed = {**defaults, "show_crosshair": False, "marker_size_percent": 180}
    assert prefs.save(changed) == changed
    assert PlotDigitizerPreferences(root=tmp_path).load() == changed
    assert prefs.path.name == "plot_digitizer.json"
    assert json.loads(prefs.path.read_text(encoding="utf-8")) == changed
    assert prefs.reset() == defaults
    assert PlotDigitizerPreferences(root=tmp_path).load() == defaults


def test_preferences_recover_corrupt_or_untrusted_entries(tmp_path):
    prefs = PlotDigitizerPreferences(root=tmp_path)
    prefs.path.parent.mkdir(parents=True)
    prefs.path.write_text("not JSON", encoding="utf-8")
    assert prefs.load() == PlotDigitizerPreferences.DEFAULTS
    prefs.path.write_text(json.dumps({
        "show_crosshair": "false", "show_magnifier": False,
        "marker_size_percent": True, "fit_images_on_open": 1,
        "mouse_wheel_zoom": False, "obsolete_option": "hi",
    }), encoding="utf-8")
    settings = prefs.load()
    assert settings["show_crosshair"] is True
    assert settings["show_magnifier"] is False
    assert settings["fit_images_on_open"] is True
    assert settings["mouse_wheel_zoom"] is False
    assert settings["marker_size_percent"] == 100
    assert "obsolete_option" not in settings
    for number in (0, 251, -1, 1e100, "200"):
        assert PlotDigitizerPreferences.normalize({"marker_size_percent": number})["marker_size_percent"] == 100


def test_settings_update_is_immediate_and_does_not_touch_dataset(tmp_path):
    from unittest.mock import Mock
    form = object.__new__(PlotDigitizerDialog)
    form._plot_preference_store = PlotDigitizerPreferences(root=tmp_path)
    form._plot_preferences = form._plot_preference_store.load()
    form._preference_refreshing = False
    form._redraw = Mock()
    form._mouse_move = Mock()
    # Must not attempt calibration, engine.set_settings, engine history, etc.
    form.engine = Mock()
    form._preference_changed("show_manual_points", False)
    assert form._plot_preferences["show_manual_points"] is False
    assert form._plot_preference_store.load()["show_manual_points"] is False
    form._redraw.assert_called_once_with()
    form._mouse_move.assert_called_once_with()
    form.engine.assert_not_called()
    form.engine.set_settings.assert_not_called()
    form._preference_changed("show_manual_points", False)
    form._redraw.assert_called_once()
    form._preference_refreshing = True
    form._preference_changed("show_manual_points", True)
    assert form._plot_preferences["show_manual_points"] is False


def test_marker_size_changes_screen_hit_area_and_hidden_types_do_not_hit():
    automatic = SimpleNamespace(visible=True, extracted_pixels=[(15, 15)], manual_points=[])
    manual = SimpleNamespace(visible=True, extracted_pixels=[],
                             manual_points=[SimpleNamespace(px=45, py=45)])
    assert marker_metrics(1, "auto", 2).radius > marker_metrics(1, "auto", .5).radius
    assert cursor_hits_marker([automatic], 15, 15, 1)
    assert not cursor_hits_marker([automatic], 15, 15, 1, show_automatic=False)
    assert not cursor_hits_marker([manual], 45, 45, 1, show_manual=False)
    assert cursor_hits_marker([manual], 45, 45, 1, show_manual=True)


def test_settings_tool_roundtrips_through_saved_project_view():
    state = normalize_workspace_state({"version": 1, "tool": "settings"})
    assert state["tool"] == "settings"
    assert normalize_workspace_state({"version": 1, "tool": "axes"})["tool"] == "axes"


def test_hiding_crosshair_restores_system_cursor():
    from unittest.mock import Mock
    cursor = Mock()
    form = SimpleNamespace(
        _canvas_cursor=cursor, winfo_exists=lambda: True, isVisible=lambda: True,
        _middle_drag=False, _cursor_canvas=(25, 25),
        _plot_preferences={**PlotDigitizerPreferences.DEFAULTS, "show_crosshair": False},
        _canvas_rect=lambda: ((10, 10), (200, 150)), _native_window_backend=None,
    )
    PlotDigitizerDialog._sync_canvas_cursor(form)
    assert cursor.update.call_args.args[0] is None
    form._plot_preferences["show_crosshair"] = True
    PlotDigitizerDialog._sync_canvas_cursor(form)
    assert cursor.update.call_args.args[0] == "blank"


def test_hidden_marker_does_not_get_selected_by_canvas_hit_test():
    from unittest.mock import Mock
    dataset = SimpleNamespace(visible=True, extracted_pixels=[(20, 25)],
                              manual_points=[SimpleNamespace(px=70, py=75)])
    form = SimpleNamespace(
        engine=SimpleNamespace(active_dataset=dataset), _fit_scale=1.0, _zoom=1.0,
        _plot_preferences={**PlotDigitizerPreferences.DEFAULTS, "show_manual_points": False},
        _marker_metrics=lambda scale, source: marker_metrics(scale, source),
    )
    assert PlotDigitizerDialog._nearest_point(form, 70, 75) is None
    assert PlotDigitizerDialog._nearest_point(form, 20, 25) == ("auto", 0)
    form._plot_preferences["show_manual_points"] = True
    assert PlotDigitizerDialog._nearest_point(form, 70, 75) == ("manual", 0)
