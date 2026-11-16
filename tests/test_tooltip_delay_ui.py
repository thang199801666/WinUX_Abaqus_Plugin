"""Verify tooltip delay on real main-app, ribbon, widget and dialog surfaces."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from DearUIQt.backends import dpg
from DearUIQt.tooltip import TOOLTIP_DELAY
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.dialogs.native_reference_tools import ReferenceChartDialog
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.services.reference_charts import make_formula_reference
from WinUx.view import WinUXView


def main():
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='tooltip-delay-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp / 'tooltip-delay-logs')}):
        view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
        digitizer = chart = None
        try:
            view._gui_runtime.show()
            digitizer = PlotDigitizerDialog(view)
            digitizer.show()
            chart = ReferenceChartDialog(view, [make_formula_reference('regex(".*U3.*")', 'Formula')], lambda result: None)
            chart.show()
            for _ in range(25):
                view.update()
                time.sleep(.01)
            listviews = [panel.listview for panel in view.panels]
            jobs = getattr(view.jobs_view, 'listview', None)
            if jobs is not None:
                listviews.append(jobs)
            for listview in listviews:
                for name in ('_body_item_tooltip', '_pinned_item_tooltip'):
                    parts = getattr(listview, name, None)
                    if parts:
                        expected_target = (
                            listview._body_canvas_widget if name == '_body_item_tooltip'
                            else listview._pinned_canvas_widget
                        )
                        assert parts['target'] is expected_target, (name, parts['target'], expected_target)
                        # Explorer draw-list rows must never own mvTooltip children.
                        # Its paint overlay is lazy and non-interactive instead.
                        assert parts['widget'].__class__.__name__ == 'ExplorerTooltipOverlay'
            count = 0
            for item in dpg.get_all_items():
                if 'Tooltip' not in str(dpg.get_item_info(item).get('type', '')):
                    continue
                options = dpg.get_item_configuration(item)
                assert abs(options['delay'] - TOOLTIP_DELAY) < .001, (item, options)
                assert options['hide_on_activity'], (item, options)
                count += 1
            assert count >= 30, count
            print('PASS: {} automatic tooltips share {:.0f} ms delay; Explorer draw-list '
                  'tooltips use lazy viewport paint overlays'.format(
                      count, TOOLTIP_DELAY * 1000), flush=True)
        finally:
            if chart is not None:
                chart.finish(None)
            if digitizer is not None:
                digitizer.destroy()
            view.request_shutdown()
            view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
