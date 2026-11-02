"""Plot history density/tooltips: abaqus python tests/test_job_plot_tooltips.py."""
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from DearUIQt.backends import dpg
from DearUIQt.widgets import QRetainedItem, QToolTip
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.ui.components.job_plots import JobPlotsWindow
from WinUx.view import WinUXView


class References:
    def snapshot(self):
        return []

    def subscribe(self, callback):
        pass

    def unsubscribe(self, callback):
        pass


def main():
    temp_root = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='winux-plot-tips-', dir=temp_root) as profile:
        with patch.dict(os.environ, {'APPDATA': profile}):
            view = WinUXView({key: lambda *a, **k: None for key in REQUIRED_CALLBACK_KEYS})
            view._gui_runtime.configureViewport(width=1000, height=700)
            view._gui_runtime.show()
            panel = JobPlotsWindow(view.primary_window_tag, '123', 'Tooltip test',
                                   reference_library=References(), after=view.after)
            QRetainedItem(view.menu_bar).hide()
            QRetainedItem(view.layout_root).hide()
            QRetainedItem(panel.root).configure(pos=(0, 0), width=980, height=650)
            panel.resize(980, 650)
            rows = [{
                'id': str(index), 'output': 'ALLIE' if index == 0 else 'OUTPUT{}'.format(index),
                'displayName': 'Internal energy: ALLIE for Whole Model with a long description'
                               if index == 0 else 'History output {}'.format(index),
                'step': 'Step-1', 'historyRegion': 'Assembly ASSEMBLY',
                'regionDescription': 'Whole model', 'description': 'Energy history data',
                'points': 1234,
            } for index in range(13)]
            panel.set_catalog({'historyOutputs': rows})
            user32 = ctypes.windll.user32

            def pump(frames=12, point=None):
                for _ in range(frames):
                    if point is not None:
                        user32.SetCursorPos(*point)
                    view.update()
                    panel.sync_layout()
                    time.sleep(.02)

            def hover_tip(target, tip):
                rect = target.globalGeometry()
                point = (int(rect.x() + min(30, rect.width() / 2)),
                         int(rect.y() + rect.height() / 2))
                assert dpg.get_item_configuration(tip.tag)['show'], 'Automatic tooltip is disabled'
                user32.SetCursorPos(*point)
                pump(40)
                assert dpg.is_item_visible(tip.tag), ('Tooltip did not appear', target.tag, tip.tag)
                if target.tag == panel._history_labels.get('0'):
                    dpg.output_frame_buffer(str(temp_root / 'job_plot_tooltip.png'))
                    pump(3)
                pump(3, (0, 0))

            try:
                pump(20)
                owner = wintypes.HWND(view._find_main_viewport_hwnd())
                user32.GetForegroundWindow.restype = wintypes.HWND
                thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                attached = user32.AttachThreadInput(current, thread, True)
                try:
                    user32.BringWindowToTop(owner)
                    user32.SetForegroundWindow(owner)
                finally:
                    if attached:
                        user32.AttachThreadInput(current, thread, False)

                boxes = [QRetainedItem(tag).globalGeometry() for tag in panel._history_rows.values()]
                pitches = [b.y() - a.y() for a, b in zip(boxes, boxes[1:])]
                assert all(14 <= pitch <= 24 for pitch in pitches), pitches
                assert max(pitches) - min(pitches) <= 1, pitches
                for button in (panel.fit_button, panel.reference_button,
                               panel.all_button, panel.none_button, panel.palette_button):
                    tip = next(tip for tip in panel._plot_tooltips if tip.target() is button)
                    assert tip.parent is button
                    hover_tip(button, tip)

                first = panel._history_tooltips['0']
                for tip in first:
                    hover_tip(tip.target(), tip)
                text = panel._history_tooltip_text(rows[0], '0')
                for value in (rows[0]['displayName'], 'Output: ALLIE', 'Step: Step-1',
                              'Region: Assembly ASSEMBLY', 'Whole model', 'Points: 1,234'):
                    assert value in text, (value, text)

                # Explicit show=False must remain available for manual tooltips.
                manual = QToolTip(panel.filter_input, show=False)
                assert not dpg.get_item_configuration(manual.tag)['show']
                manual.delete()

                panel.all_button.click()
                assert len(panel.selected_ids) == 13
                panel.none_button.click()
                assert not panel.selected_ids
                panel.filter_input.setText('ALLIE')
                pump(3)
                panel._apply_filter()
                pump(3)
                assert dpg.is_item_shown(panel._history_rows['0'])
                assert all(not dpg.is_item_shown(panel._history_rows[str(i)]) for i in range(1, 13))
                old_tips = list(first)
                panel.set_catalog({'historyOutputs': rows})
                pump()
                assert all(tip._deleted and not dpg.does_item_exist(tip.tag) for tip in old_tips)
                assert len(panel._history_tooltips) == 13
                hover_tip(panel._history_tooltips['0'][1].target(), panel._history_tooltips['0'][1])
                print('PASS: five plot button tooltips, full history metadata on checkbox/text, '
                      'compact rows, selection and tooltip cleanup/rebuild', flush=True)
            finally:
                panel.close()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
