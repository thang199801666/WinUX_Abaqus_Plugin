"""Job Viewer menu ordering/permissions and Check Nodes action routing."""
import sys

import pytest

from tests.test_job_actions import fixture, drain
from WinUx.controllers.job_actions import CHECK_NODES_COMMAND


@pytest.mark.windows_native
@pytest.mark.skipif(sys.platform != 'win32', reason='Requires native DearPyGui')
def test_check_nodes_follows_details_and_other_users_jobs_can_open_console():
    import dearpygui.dearpygui as dpg
    from WinUx.ui.components.jobs_view import JobsView
    from types import SimpleNamespace

    app, actions, _, callbacks, _ = fixture()
    app._selected_job_values.return_value = None
    dpg.create_context()
    try:
        dpg.configure_app(manual_callback_management=True)
        dpg.create_viewport(title='Job Viewer node status', width=1000, height=600)
        window = dpg.add_window(width=1000, height=600)
        jobs = JobsView(window, callbacks={'job_command': actions.job_command, 'job_user': lambda: 'owner'})
        dpg.setup_dearpygui()
        dpg.show_viewport()
        jobs.display([SimpleNamespace(job_id='1.server', name='analysis', user='another',
                                      tokens='4', status='R', elapsed='1m')])
        dpg.render_dearpygui_frame()
        menu = jobs.listview.item_menu_spec
        details = next(index for index, item in enumerate(menu) if item.get('action') == 'details')
        assert menu[details + 1]['action'] == 'check_nodes'
        assert menu[details + 1]['label'] == 'Check Nodes'
        jobs._context_open([jobs.listview.items[0]])
        assert next(item for item in menu if item.get('action') == 'check_nodes')['enabled']
        assert not next(item for item in menu if item.get('action') == 'cancel')['enabled']
        jobs.listview._context_item_index = 0
        jobs.listview._on_item_menu_action(None, None, 'check_nodes')
        app.console_command.assert_not_called()
        drain(callbacks)
        app.console_command.assert_called_once_with(CHECK_NODES_COMMAND)
        app.view.set_console_visible.assert_called_once_with(True, persist=True, request_login=False)
    finally:
        dpg.destroy_context()
