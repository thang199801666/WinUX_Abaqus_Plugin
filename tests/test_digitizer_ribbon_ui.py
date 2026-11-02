"""Rendered ribbon tiles, labels, group spacing and direct command routing."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))
from PIL import Image, ImageDraw
from DearUIQt.backends import dpg
from DearUIQt.widgets import QRetainedItem
from DearUIQt.ribbon.textures import RibbonTileTextures
from WinUx.controllers.callbacks import REQUIRED_CALLBACK_KEYS
from WinUx.plotdigitizer.ui.dialog import PlotDigitizerDialog
from WinUx.resources import icon_path
from WinUx.view import WinUXView


def main():
    original_icons = {path: path.read_bytes() for path in
                      (ROOT / 'WinUx' / 'Resources' / 'plotdigitizer_icons').glob('*.png')}
    temp = Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'opencode'
    with tempfile.TemporaryDirectory(prefix='digitizer-ribbon-', dir=temp) as profile, \
            patch.dict(os.environ, {'APPDATA': profile, 'WINUX_LOG_DIR': str(temp / 'digitizer-ribbon-logs')}):
        runtime = None
        if '--standalone' in sys.argv:
            from WinUx.ui.hosting.floating_runtime import FloatingDialogRuntime
            runtime = FloatingDialogRuntime(Mock(), iter(()), {
                'kind': 'plotdigitizer', 'title': 'Plot Digitizer', 'visible': True,
                'payload': {}, 'width': 1240, 'height': 800})
            runtime.gui.createContext(manual_callbacks=True)
            runtime._publish_requested = runtime._commit_requested = True
            runtime._build()
            view = runtime.view
        else:
            view = WinUXView({key: lambda *a, **kw: None for key in REQUIRED_CALLBACK_KEYS})
        dialog = None
        try:
            if runtime is not None:
                dialog = runtime.form
            else:
                view._gui_runtime.show()
                dialog = PlotDigitizerDialog(view)
                dialog.show()
            ribbon = dialog.ribbon
            assert not hasattr(dialog, 'clean_markers_button'), 'Duplicate sidebar Clean command'
            assert not hasattr(dialog, 'clean_project_button'), 'Duplicate sidebar Clean command'

            def pump(count=18):
                for _ in range(count):
                    if runtime is not None:
                        runtime._drain_form_callbacks()
                        view.drain()
                        runtime.gui.renderFrame()
                        view.mark_presented()
                    else:
                        view.update()
                    time.sleep(.01)

            def rect(tag):
                value = QRetainedItem(tag).globalGeometry()
                return value.x(), value.y(), value.width(), value.height()

            def button_rect(record):
                return rect(record.get('container') or record['tag'])

            pump(35)
            expected_labels = {
                'box': 'Select Plot', 'read_axes': 'Read Ticks', 'edit': 'Edit Points',
                'samples': 'Resample',
                'clean': 'Clear', 'pick_color': 'Pick Color', 'extract': 'Extract',
                'view_data': 'View Data', 'delete_points': 'Delete', 'data_delete': 'Delete',
            }
            for key, label in expected_labels.items():
                assert ribbon._buttons[key]['label'] == label, (key, ribbon._buttons[key]['label'])
            assert set(ribbon._tabs) == {'home', 'data'}
            assert not {'fit', 'one_to_one', 'zoom_out', 'zoom_in'} & set(ribbon._buttons)
            assert ribbon.tab_render_style == 'underline'
            font = RibbonTileTextures._font(ribbon.TILE_FONT_SIZE)
            draw = ImageDraw.Draw(Image.new('RGBA', (84, ribbon.LARGE_BUTTON_HEIGHT)))
            ink_bottoms = {}
            for record in ribbon._buttons.values():
                tile_width = record['width']
                assert tile_width == (84 if record['key'] == 'box' else 64), record['key']
                assert record.get('large_tile'), record['key']
                assert dpg.does_item_exist(record['tile_texture'])
                pixels = dpg.get_value(record['tile_texture'])
                icon_alpha = Image.new('L', (tile_width, 35))
                icon_alpha.putdata([round(pixels[(y * tile_width + x) * 4 + 3] * 255)
                                    for y in range(35) for x in range(tile_width)])
                bounds = icon_alpha.getbbox()
                assert bounds, (record['key'], 'missing icon')
                icon_width, icon_height = bounds[2] - bounds[0], bounds[3] - bounds[1]
                assert 27 <= max(icon_width, icon_height) <= 28, (
                    record['key'], 'visible icon size', bounds)
                assert abs((bounds[0] + bounds[2]) / 2 - tile_width / 2) <= 1
                assert abs((bounds[1] + bounds[3]) / 2 - 19) <= 1
                ink_rows = [y for y in range(35, ribbon.LARGE_BUTTON_HEIGHT - 8)
                            if any(pixels[(y * tile_width + x) * 4 + 3] > .05 for x in range(tile_width))]
                assert ink_rows, (record['key'], 'missing label ink')
                ink_bottoms[record['key']] = max(ink_rows) + 1
                assert 10 <= ribbon.LARGE_BUTTON_HEIGHT - ink_bottoms[record['key']] <= 12, (
                    record['key'], 'excess padding inside button texture', ink_bottoms[record['key']])
                path = icon_path(record['image'])
                expected = 'save_project' if record['key'] == 'save_project_as' else {
                    'fit': 'fit_view', 'box': 'plot_area', 'edit': 'edit_points',
                    'pick_color': 'sample_color',
                    'extract': 'extract_points', 'read_axes': 'calibrate_axes',
                    'data_delete': 'delete_points', 'data_undo': 'undo', 'data_redo': 'redo',
                    'smooth_curve': 'reduce_samples', 'samples': 'reduce_samples', 'clean': 'delete_item',
                }.get(record['key'], record['key'])
                assert record['image'] == dialog._icon(expected), record['image']
                with Image.open(path) as image:
                    bounds = image.getchannel('A').getbbox()
                    assert bounds, path
                lines = RibbonTileTextures._wrapped_lines(
                    record['label'], draw=draw, font=font, max_width=tile_width - 10)
                assert len(lines) == 1, (record['key'], lines)

            # Runtime updates must retain the same font and compact ink padding.
            save_as = ribbon._buttons['save_project']
            texture = save_as['tile_texture']
            ribbon.set_button_label('save_project', save_as['label'])
            assert save_as['tile_texture'] == texture
            ribbon.set_button_image('save_project', save_as['image'])
            assert save_as['tile_texture'] == texture
            ribbon._apply_button_display_geometry(save_as)
            assert save_as['tile_texture'] == texture

            for key in ('undo', 'redo', 'export_csv', 'edit', 'delete_points', 'smooth_curve', 'samples',
                        'box', 'pick_color',
                        'read_axes', 'extract', 'view_data', 'data_delete', 'data_undo', 'data_redo'):
                record = ribbon._buttons[key]
                assert not record['enabled'], (key, 'unavailable command should be disabled')
                disabled_texture = record['tile_texture']
                gray = dpg.get_value(disabled_texture)
                visible = [index for index in range(0, record['width'] * 35 * 4, 4) if gray[index + 3] > .05]
                assert visible
                assert all(max(gray[index:index + 3]) - min(gray[index:index + 3]) < .001
                           for index in visible), (key, 'disabled icon retained color')
                label_pixels = [index for index in range(record['width'] * 35 * 4, len(gray), 4) if gray[index + 3] > .05]
                expected = ribbon.visual_style.disabled_text
                assert all(abs(gray[index] - expected[0] / 255) < .005 for index in label_pixels)
                callback = record['callback']
                blocked = Mock()
                record['callback'] = blocked
                ribbon._button_clicked(key)
                blocked.assert_not_called()
                assert not dpg.get_item_configuration(record['tag'])['enabled']
                ribbon.set_button_enabled(key, True)
                colored_texture = record['tile_texture']
                colored = dpg.get_value(colored_texture)
                assert colored_texture != disabled_texture
                assert any(max(colored[index:index + 3]) - min(colored[index:index + 3]) > .05
                           for index in visible), (key, 'enabled icon did not restore color')
                assert gray[3::4] == colored[3::4], (key, 'disabled state changed icon/label shape')
                ribbon._button_clicked(key)
                blocked.assert_called_once()
                ribbon.set_button_enabled(key, False)
                assert record['tile_texture'] == disabled_texture
                ribbon.set_button_label(key, record['label'])
                ribbon.set_button_image(key, record['image'])
                ribbon._apply_button_display_geometry(record)
                assert record['tile_texture'] == disabled_texture
                record['callback'] = callback

            assert [key for tab, key in ribbon._groups if tab == 'home'] == [
                'file', 'plot_area', 'extract', 'data', 'history', 'tools']
            assert 'process_points' not in ribbon._buttons
            assert [r['key'] for r in ribbon._buttons.values() if r['tab'] == 'home' and r['group'] == 'file'] == [
                'open_image', 'save_project', 'clean']
            assert [r['key'] for r in ribbon._buttons.values() if r['tab'] == 'home' and r['group'] == 'extract'] == [
                'pick_color', 'extract', 'edit', 'delete_points']
            assert [r['key'] for r in ribbon._buttons.values() if r['tab'] == 'data'] == [
                'data_delete', 'smooth_curve', 'samples', 'export_csv', 'data_undo', 'data_redo']
            assert [r['key'] for r in ribbon._buttons.values() if r['tab'] == 'home' and r['group'] == 'tools'] == ['settings']
            for key in ('smooth_curve', 'samples'):
                assert not ribbon._buttons[key].get('menu_indicator')
                assert ribbon._buttons[key]['callback'].__name__ == (
                    '_open_samples_dialog' if key == 'samples' else '_' + key)
            assert not {'increase_samples', 'reduce_samples', 'simplify_samples'} & set(ribbon._buttons)
            for key in ('open_image', 'save_project', 'clean'):
                assert ribbon._buttons[key]['menu_indicator']
                record = ribbon._buttons[key]
                assert record['split'] and record['tile_split']
                mx, my, mw, mh = rect(record['tag'])
                ax, ay, aw, ah = rect(record['arrow'])
                assert mh == ribbon.LARGE_BUTTON_HEIGHT - ribbon.MENU_ARROW_HEIGHT
                assert ah == ribbon.MENU_ARROW_HEIGHT
                assert abs(mx - ax) <= 1 and abs(ay - my - mh) <= 1, (key, (mx, my, mw, mh), (ax, ay, aw, ah))
                assert '▾' not in record['label']
                pixels = dpg.get_value(record['tile_texture'])
                # Arrow is triangle pixels below the caption, not a font glyph.
                tile_width = record['width']
                cx, y = tile_width // 2, ribbon.LARGE_BUTTON_HEIGHT - 7
                assert pixels[(y * tile_width + cx - 3) * 4 + 3] > .9
                assert pixels[((y + 3) * tile_width + cx) * 4 + 3] > .9
                assert pixels[((y + 3) * tile_width + cx - 3) * 4 + 3] == 0
            assert [r['key'] for r in ribbon._buttons.values()
                    if r['tab'] == 'home' and r['group'] == 'plot_area'] == ['box', 'read_axes']
            assert len([r for r in ribbon._buttons.values() if r['tab'] == 'home']) == 13
            with patch.object(dialog, '_begin_pick') as pick:
                ribbon.set_button_enabled('pick_color', True)
                ribbon._button_clicked('pick_color')
                pick.assert_called_once_with('curve')
                ribbon.set_button_enabled('pick_color', False)
            with patch.object(dialog, '_file_picker') as picker:
                ribbon._button_clicked('open_image')
                picker.assert_called_once()
                assert ribbon._buttons['open_image']['current_action'] == 'open_image_0'

            for width in (1000, 1100, 1380):
                dialog.resize(width, 800)
                for tab in ('home', 'data'):
                    ribbon.set_active_tab(tab)
                    pump(25)
                    buttons = [record for record in ribbon._buttons.values() if record.get('tab') == tab]
                    geometry = [button_rect(record) for record in buttons]
                    rx, ry, rw, rh = rect(ribbon.tag)
                    assert all(x >= rx and x + w <= rx + rw + 1 for x, y, w, h in geometry), (
                        width, tab, 'commands clipped by ribbon edge', (rx, rw), geometry)
                    assert len({round(r[3]) for r in geometry}) == 1, geometry
                    assert max(r[1] for r in geometry) - min(r[1] for r in geometry) <= 1, geometry
                    groups = [group for (key, _), group in ribbon._groups.items() if key == tab]
                    captions = [rect(group['footer']) for group in groups]
                    if '--geometry' in sys.argv:
                        print(tab, [(group['key'], rect(group['tag']), rect(group['controls']),
                                    rect(group['row']), rect(group['footer_row']),
                                    dpg.get_item_configuration(group['footer_row']).get('pos'),
                                    rect(group['footer'])) for group in groups],
                              'buttons', geometry, flush=True)
                    assert max(r[1] for r in captions) - min(r[1] for r in captions) <= 1
                    for group in groups:
                        assert dpg.is_item_shown(group['tag']), (width, tab, group['key'])
                        gx, gy, gw, gh = rect(group['controls'])
                        px, py, pw, ph = rect(group['tag'])
                        members = [button_rect(record) for record in buttons if record['group'] == group['key']]
                        for x, y, w, h in members:
                            assert x >= gx and y >= gy and x + w <= gx + gw + 1 and y + h <= gy + gh + 1, (group['key'], members, (gx, gy, gw, gh))
                        for first, second in zip(members, members[1:]):
                            assert abs(second[0] - first[0] - first[2] - ribbon.COMMAND_GAP) <= 1
                        fx, fy, fw, fh = rect(group['footer'])
                        # The caption must fit its clipping ancestors, not just
                        # have a correct un-clipped geometry below the buttons.
                        assert fy >= py and fy + fh <= py + ph - 3, (
                            width, tab, group['key'], 'group caption clipped',
                            (fx, fy, fw, fh), (px, py, pw, ph))
                        bx, by, bw, bh = rect(ribbon.body)
                        assert fy + fh <= by + bh - 3, (width, tab, group['key'], 'caption outside body')
                        assert fy + fh <= ry + rh - 3, (width, tab, group['key'], 'caption outside ribbon')
                        center = (members[0][0] + members[-1][0] + members[-1][2]) / 2
                        assert abs(fx + fw / 2 - center) <= 2, (group['key'], 'caption off center', fx + fw / 2, center)
                        assert abs(center - (px + pw / 2)) <= 1, (group['key'], 'unequal side padding')
                        top_gap = members[0][1] - py
                        caption_gap = fy - (members[0][1] + members[0][3])
                        assert 4 <= top_gap <= 6, (group['key'], 'missing top inset', top_gap)
                        assert 1 <= caption_gap <= 3, (group['key'], 'excess caption gap', caption_gap)
                        for record in buttons:
                            if record['group'] != group['key']:
                                continue
                            x, y, w, h = button_rect(record)
                            visible_gap = fy - (y + ink_bottoms[record['key']] * h / ribbon.LARGE_BUTTON_HEIGHT)
                            assert 11 <= visible_gap <= 15, (record['key'], 'visible text-to-caption gap', visible_gap)

            ribbon.set_active_tab('home')
            pump()
            menu_actions = {
                'open_image': ('open_image_0', 'open_image_1'),
                'save_project': ('save_project_0', 'save_project_1'),
                'clean': ('clean_0', 'clean_2'),
            }
            for key, actions in menu_actions.items():
                menu = ribbon._buttons[key]['menu']
                ribbon._popup_menu(key, menu)
                pump(6)
                for action in actions:
                    icon = menu._find_spec(action)['icon']
                    assert icon is not None and dpg.does_item_exist(icon), (key, action, 'missing texture')
                    rendered = menu._items[action]['icon']
                    assert rendered is not None and dpg.does_item_exist(rendered), (key, action, 'icon not rendered')
                    assert rect(menu._rows[action])[3] == 36
                    assert rect(rendered)[2:] == (24, 24)
                    label = menu._items[action]['label']
                    assert 'mvText' in dpg.get_item_info(label)['type']
                    assert dpg.get_item_configuration(label)['show'], (key, action, 'hidden menu label')
                    assert dpg.get_value(label) == menu._find_spec(action)['label']
                    assert menu._menu_font is not None and menu._menu_font.pixel_size == 16
                    assert dpg.get_item_font(label) == menu._menu_font.nativeId()
                    assert dpg.get_item_state(label)['visible'], (key, action, 'label not rendered')
                    lx, ly, lw, lh = rect(label)
                    rx, ry, rw, rh = rect(menu._rows[action])
                    assert lw > 0 and lh > 0 and rx <= lx and ry <= ly, (key, action, 'invalid text bounds')
                    assert lx + lw <= rx + rw and ly + lh <= ry + rh, (key, action, 'clipped menu text')
                menu.hide()
            with patch.object(dialog, '_file_picker') as picker:
                ribbon._buttons['save_project']['menu'].triggered.emit('save_project_1')
                picker.assert_called_once()
                assert picker.call_args.kwargs['save']
            assert not ribbon._buttons['undo']['enabled']
            with patch.object(dialog, '_file_picker') as picker:
                ribbon._buttons['open_image']['menu'].triggered.emit('open_image_0')
                picker.assert_called_once()
            with patch.object(dialog, '_request_clean') as clean:
                menu = ribbon._buttons['clean']['menu']
                menu.triggered.emit('clean_0')
                clean.assert_called_once_with('markers')
                menu.triggered.emit('clean_2')
                assert clean.call_args.args == ('project',)
                assert ribbon._buttons['clean']['current_action'] == 'clean_2'
                assert ribbon._buttons['clean']['label'] == 'New'
                ribbon._button_clicked('clean')
                assert clean.call_count == 3 and clean.call_args.args == ('project',)
                menu._row_clicked(user_data='clean_2')  # Selecting the current item must execute again.
                assert clean.call_count == 4
                menu._row_clicked(user_data='clean_0')
                assert ribbon._buttons['clean']['label'] == 'Clear'
                ribbon._button_clicked('clean')
                assert clean.call_count == 6 and clean.call_args.args == ('markers',)
            with patch.object(dialog, '_file_picker') as picker:
                menu = ribbon._buttons['open_image']['menu']
                menu._row_clicked(user_data='open_image_1')
                assert ribbon._buttons['open_image']['label'] == 'Open Project'
                assert ribbon._buttons['open_image']['image'] == dialog._icon('load_project')
                assert dpg.get_item_configuration(ribbon._buttons['open_image']['arrow'])['texture_tag'] == ribbon._buttons['open_image']['tile_texture']
                ribbon._button_clicked('open_image')
                menu._row_clicked(user_data='open_image_1')
                assert picker.call_count == 3
                assert picker.call_args.kwargs['extensions'] == ('.pdg', '.json')
                picker.reset_mock()
                arrow = ribbon._buttons['open_image']['arrow']
                dpg.get_item_configuration(arrow)['callback'](arrow, None, None)
                pump(5)
                picker.assert_not_called()  # Arrow opens only; it never runs the current action.
                menu.hide()
                menu._row_clicked(user_data='open_image_0')
                ribbon._button_clicked('open_image')
                assert picker.call_count == 2
                assert ribbon._buttons['open_image']['current_action'] == 'open_image_0'
                picker.reset_mock()
                ribbon.set_button_enabled('open_image', False)
                ribbon._button_clicked('open_image')
                menu._row_clicked(user_data='open_image_1')
                dpg.get_item_configuration(arrow)['callback'](arrow, None, None)
                picker.assert_not_called()
                assert ribbon._buttons['open_image']['current_action'] == 'open_image_0'
                ribbon.set_button_enabled('open_image', True)
            with patch.object(dialog, '_file_picker') as picker:
                ribbon._button_clicked('save_project')  # Save As was the last selection above.
                assert picker.call_count == 1 and picker.call_args.kwargs['save']
                assert ribbon._buttons['save_project']['label'] == 'Save As'
            # The last choice is independent for each split button.
            assert ribbon._buttons['clean']['current_action'] == 'clean_0'
            assert ribbon._buttons['save_project']['current_action'] == 'save_project_1'
            dialog.engine.apply_image(Image.new('RGB', (200, 200), 'white'), 'ribbon.png')
            dialog._refresh_dataset_controls()
            assert ribbon._buttons['pick_color']['enabled']
            assert not ribbon._buttons['extract']['enabled']
            assert not dialog.control_wrapper(dialog.extract_button).isEnabled()
            with patch.object(dialog, '_start_extraction') as extract:
                ribbon._button_clicked('extract')
                dialog._extract_curve()
                extract.assert_not_called()
            ribbon._button_clicked('pick_color')
            assert dialog._pick_mode == 'curve'
            assert dialog._canvas_cursor.mode == 'color_pick'
            picker = dialog._canvas_cursor._handles.get('color_pick')
            assert picker and picker == dialog._canvas_cursor._handles.get('color_pick')
            assert picker != dialog._canvas_cursor._handles.get('arrow')
            with patch.object(dialog, '_mouse_in_canvas', return_value=True), \
                    patch.object(dialog, '_canvas_to_image', return_value=(20, 20)), \
                    patch.object(dialog, '_focus_canvas_keyboard'):
                dialog._mouse_left()
            assert dialog.engine.active_dataset.curve_rgb == (255, 255, 255)
            dialog._refresh_dataset_controls()
            assert ribbon._buttons['extract']['enabled']
            assert dialog.control_wrapper(dialog.extract_button).isEnabled()
            dialog.engine.undo()
            dialog._refresh_dataset_controls()
            assert dialog.engine.active_dataset.curve_rgb is None
            assert not ribbon._buttons['extract']['enabled']
            assert not dialog.control_wrapper(dialog.extract_button).isEnabled()
            dialog.engine.redo()
            dialog._refresh_dataset_controls()
            assert ribbon._buttons['extract']['enabled']
            assert dialog._pick_mode is None, 'Sampling must exit after a successful color pick'
            assert dialog._canvas_cursor.mode != 'color_pick'
            ribbon._button_clicked('pick_color')
            assert dialog._pick_mode == 'curve'
            assert dialog._canvas_cursor.mode == 'color_pick'
            with patch.object(dialog, '_request_close_confirmation') as close:
                dialog._close_from_escape()
                close.assert_not_called()
            assert dialog._pick_mode is None
            assert dialog._canvas_cursor.mode != 'color_pick'
            dialog._refresh_workflow()
            ribbon._button_clicked('view_data')
            assert dialog._active_tool == 'data' and ribbon.active_tab() == 'data'
            with patch.object(dialog, '_start_extraction') as extract:
                ribbon._button_clicked('extract')
                extract.assert_called_once_with(auto_detect=False)
            assert dialog._active_tool == 'extract' and ribbon.active_tab() == 'home'
            dialog.engine.set_plot_rect_with_corner_anchors((20, 20, 180, 180), detect_ticks=False)
            dialog._refresh_calibration_actions()
            with patch.object(dialog, '_start_tick_calibration') as read:
                ribbon._button_clicked('read_axes')
                read.assert_called_once_with((20, 20, 180, 180))
            assert dialog._active_tool == 'axes'
            before_edit = dialog.engine._snapshot()
            dialog.engine.add_manual_point(30, 30)
            after_edit = dialog.engine._snapshot()
            dialog._refresh_history_commands()
            assert ribbon._buttons['undo']['enabled'] and ribbon._buttons['data_undo']['enabled']
            ribbon._button_clicked('data_undo')
            assert dialog.engine._snapshot() == before_edit
            assert ribbon._buttons['redo']['enabled'] and ribbon._buttons['data_redo']['enabled']
            ribbon._button_clicked('data_redo')
            assert dialog.engine._snapshot() == after_edit
            from WinUx.plotdigitizer.core.models import DataPoint
            dialog.engine.active_dataset.manual_points = [DataPoint(10, 10), DataPoint(20, 20)]
            dialog._refresh_point_actions()
            assert ribbon._buttons['samples']['enabled']
            assert not ribbon._buttons['smooth_curve']['enabled']
            dialog.engine.active_dataset.manual_points.append(DataPoint(30, 30))
            dialog._refresh_point_actions()
            assert ribbon._buttons['smooth_curve']['enabled']
            assert ribbon._buttons['samples']['enabled']
            dialog._smart_runner._pending = True
            dialog._refresh_dataset_controls()
            assert not ribbon._buttons['extract']['enabled']
            dialog._refresh_point_actions()
            assert all(not ribbon._buttons[key]['enabled'] for key in (
                'samples', 'smooth_curve'))
            dialog._smart_runner._pending = False
            dialog.engine.active_dataset.locked = True
            dialog._refresh_dataset_controls()
            assert not ribbon._buttons['pick_color']['enabled']
            assert not ribbon._buttons['extract']['enabled']
            dialog._refresh_point_actions()
            assert all(not ribbon._buttons[key]['enabled'] for key in (
                'samples', 'smooth_curve'))
            assert all(path.read_bytes() == data for path, data in original_icons.items()), 'Original icon files changed'
            print('PASS: disabled gray icons/text, blocked clicks and restored color; equal icon bounds, untouched originals, compact layout, '
                   'contained Home/Data commands at 1000/1100/1380 px, workflow routing, large dropdown rows, independent main/arrow hit areas, '
                   'repeat-last actions and confirmation routing', flush=True)
        finally:
            if runtime is not None:
                view._dispatcher.close()
                if runtime.native:
                    runtime.native.set_visible(False)
                    runtime.native.restore_close_handler()
                    runtime.native.close_activation_guard()
                runtime.gui.destroy()
            else:
                if dialog is not None:
                    dialog.destroy()
                view.request_shutdown()
                view._gui_runtime.destroy()


if __name__ == '__main__':
    main()
