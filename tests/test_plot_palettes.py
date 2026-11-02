"""Palette preferences and real retained plots: abaqus python tests/test_plot_palettes.py."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_dock_forms import PlotDockForm
from WinUx.dialogs.native_dock_hosts import PlotDockHost
from WinUx.preferences.plot_appearance import PlotAppearancePreferences
from WinUx.services.plot_palettes import (
    PALETTES, EXCEL_THEME_KEYS, AUTO_SEQUENCE_KEYS, PLOT_THEME_KEYS,
    normalize_palette, normalize_plot_theme, palette_colors, theme_swatches,
)
from WinUx.ui.components.job_plots import JobPlotsWindow
from WinUx.view import WinUXView


class References:
    items = [{'id': 'ref', 'name': 'Reference', 'enabled': True,
              'points': [[0, 1], [1, 3]]}]

    def snapshot(self):
        return self.items

    def subscribe(self, callback):
        pass

    def unsubscribe(self, callback):
        pass


def main():
    for invalid in (None, [], {}, 42, '', 'unknown'):
        assert normalize_palette(invalid) == 'default'
    assert normalize_palette(' TABLEAU ') == 'tableau'
    assert normalize_plot_theme(' TABLEAU ') == 'default'
    assert normalize_plot_theme(' EXCEL_GREEN ') == 'excel_green'
    assert normalize_plot_theme(' AUTO_RGB ') == 'auto_rgb'
    for key in PALETTES:
        colors = palette_colors(key)
        assert len(colors) >= 8 and len(set(colors)) == len(colors)
        assert all(len(color) == 4 and color[3] == 255 and
                   all(0 <= value <= 255 for value in color) for color in colors)
    # Office chart series use the six accent swatches, not the dark/light
    # document colours that occupy the first two boxes in Excel's gallery.
    assert palette_colors('default')[:6] == (
        (94, 153, 211, 255), (231, 126, 60, 255), (166, 164, 167, 255),
        (252, 192, 0, 255), (71, 114, 193, 255), (112, 174, 65, 255))
    assert theme_swatches('default')[:2] == (
        (65, 85, 112, 255), (236, 227, 232, 255))
    assert EXCEL_THEME_KEYS == (
        'default', 'office_2007_2010', 'grayscale', 'blue_warm', 'excel_blue',
        'blue_ii', 'blue_green', 'excel_green', 'green_yellow', 'yellow',
        'yellow_orange', 'excel_orange', 'orange_red', 'red_orange', 'red',
        'red_violet', 'violet', 'violet_ii', 'median', 'paper', 'marquee')
    assert AUTO_SEQUENCE_KEYS == ()
    assert PLOT_THEME_KEYS == EXCEL_THEME_KEYS
    assert normalize_plot_theme(' AUTO_RGB ') == 'marquee'
    assert normalize_plot_theme(' EXCEL_PASTEL ') == 'paper'
    assert palette_colors('red_violet')[:3] == (
        (229, 44, 145, 255), (204, 44, 212, 255), (79, 166, 219, 255))
    assert all(len(palette_colors(key)) == 12 for key in EXCEL_THEME_KEYS)


    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-palettes-', dir=temp_root) as profile:
        prefs = PlotAppearancePreferences(root=profile)
        assert prefs.load_palette() == 'default'
        prefs.save_palette('excel_green')
        assert PlotAppearancePreferences(root=profile).load_palette() == 'excel_green'
        # Old pre-Theme palette ids migrate to the Excel Office default.
        prefs._store.save({'palette': 'viridis'})
        assert PlotAppearancePreferences(root=profile).load_palette() == 'default'
        prefs._store.save({'palette': ['corrupt']})
        assert prefs.load_palette() == 'default'
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.show()
            events = []
            panel = JobPlotsWindow(view.primary_window_tag, 'palette-test', 'Palettes',
                                   reference_library=References(), after=view.after,
                                   on_palette_change=events.append)
            reopened = None
            try:
                panel.set_catalog({'historyOutputs': [
                    {'id': 'ke', 'output': 'ALLKE', 'displayName': 'Kinetic energy'},
                    {'id': 'ie', 'output': 'ALLIE', 'displayName': 'Internal energy'}]})
                panel.set_selected_ids(['ke', 'ie'], notify=False)
                panel.update_frame({'series': [
                    {'id': key, 'points': [[0, 0], [1, 2]]} for key in ('ke', 'ie')]})
                for _ in range(10):
                    view.update()
                    panel.sync_layout()
                dpg.set_axis_limits(panel._x_axis_widget.tag, -2, 5)
                dpg.set_axis_limits(panel._y_axis_widget.tag, -3, 7)
                view.update()
                axes = [panel._x_axis_widget.tag, panel._y_axis_widget.tag]
                limits = [dpg.get_axis_limits(axis) for axis in axes]
                series = list(panel._series_objects.values()) + list(panel._reference_series_objects.values())
                original = [(item.tag, dpg.get_value(item.tag), item._line_color,
                             item._line_width, item._marker) for item in series]
                assert len(series) == 3
                for key in PLOT_THEME_KEYS:
                    panel._palette_menu_triggered(key)
                    view.update()
                    assert [dpg.get_axis_limits(axis) for axis in axes] == limits
                    for item, (tag, data, _color, width, marker) in zip(series, original):
                        assert item.tag == tag and dpg.get_value(tag) == data
                        assert item._line_width == width and item._marker == marker
                    assert panel._series_objects['ke']._line_color == palette_colors(key)[0]
                    assert panel._series_objects['ie']._line_color == palette_colors(key)[1]
                    checked = [action['id'] for action in panel._palette_menu._actions if action['checked']]
                    assert checked == [key]
                    assert panel.native_snapshot()['palette'] == key
                panel.set_palette('default')
                assert [item._line_color for item in series] == [row[2] for row in original]
                panel.set_palette('red_violet')
                assert PlotAppearancePreferences().load_palette() == 'red_violet'
                reopened = JobPlotsWindow(view.primary_window_tag, 'palette-reopened', '',
                                         reference_library=References(), after=view.after)
                assert reopened._palette_id == 'excel_dark'

                # Detached UI emits one event; snapshots do not echo it back.
                child_events = []
                reopened.on_palette_change = lambda key: child_events.append(('palette', {'palette': key}))
                reopened.set_palette('excel_pastel', persist=False)
                event, message = child_events.pop()
                PlotDockHost.handle_event(SimpleNamespace(panel=panel), event, message)
                assert panel._palette_id == 'excel_pastel'
                snapshot = panel.native_snapshot()
                child_events.clear()
                form = SimpleNamespace(panel=reopened, references=reopened.reference_library,
                                       _catalog_snapshot=None, _emit=lambda *a, **kw: None)
                PlotDockForm.apply_snapshot(form, snapshot)
                assert reopened._palette_id == 'excel_pastel' and not child_events
                assert reopened.native_snapshot()['series'] == snapshot['series']
                count = len(events)
                assert not panel.set_palette('excel_pastel') and len(events) == count
                panel._open_palette_menu()
                view.update()
                assert panel._palette_menu.isVisible()
                assert panel.palette_button.text() == 'Theme'
                menu_actions = panel._palette_menu._actions
                selectable = [action['id'] for action in menu_actions if not action.get('separator')]
                assert selectable == list(PLOT_THEME_KEYS)
                separators = [action for action in menu_actions if action.get('separator')]
                assert len(separators) == 0
                panel._palette_menu_triggered('auto_rgb')
                view.update()
                assert panel._series_objects['ke']._line_color == palette_colors('auto_rgb')[0]
                assert panel._series_objects['ie']._line_color == palette_colors('auto_rgb')[1]
                print('PASS: Excel themes + automatic color sequences, preference migration/persistence, '
                      'live recoloring without data/axis/style loss, raised Theme control, grouped menu '
                      'state and detached synchronization')
            finally:
                if reopened is not None:
                    reopened.close()
                panel.close()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
