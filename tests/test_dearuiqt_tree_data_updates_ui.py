"""Standalone native QTreeView dataChanged regression; --pointer clicks nodes."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.core import Qt
from DearUIQt.gui import QStandardItem, QStandardItemModel
from DearUIQt.widgets import QApplication, QMainWindow
from DearUIQt.modelview import QTreeView


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    application = QApplication(after=host.after)
    window = model = None
    pointer = '--pointer' in sys.argv
    cursor = wintypes.POINT()
    user32 = ctypes.windll.user32
    if pointer:
        user32.GetCursorPos(ctypes.byref(cursor))
    try:
        window = QMainWindow('DearUIQt tree data updates', width=520, height=360,
                             after=host.after, backend=runtime.backend)
        model = QStandardItemModel()
        parent = QStandardItem('parent')
        parent.setData('parent', Qt.UserRole)
        children = [QStandardItem('child ' + str(i)) for i in range(5)]
        for i, child in enumerate(children): child.setData('child' + str(i), Qt.UserRole)
        parent.appendRows(children)
        model.appendRow(parent)
        tree = QTreeView(parent=window, height=280, after=host.after)
        tree.setKeyRole(Qt.UserRole)
        tree.setModel(model)
        runtime.createViewport(title='DearUIQt tree data updates', width=520, height=360)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def pump(count=5):
            for _ in range(count):
                runtime.backend.run_callbacks(runtime.callbackQueue())
                host.pump()
                runtime.renderFrame()
                time.sleep(.01)
        tree.expand('parent')
        pump(15)
        if pointer:
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.FindWindowW.restype = wintypes.HWND
            hwnd = user32.FindWindowW(None, 'DearUIQt tree data updates')
            assert hwnd
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
            pump(8)
            def click(key):
                native = tree._native_by_key[key]
                pos = runtime.backend.get_item_rect_min(native)
                size = runtime.backend.get_item_rect_size(native)
                point = wintypes.POINT(int(pos[0] + 30), int(pos[1] + size[1] / 2))
                user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point))
                user32.SetCursorPos(point.x, point.y)
                pump(3)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                pump(3)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                pump(8)
            click('child2')
        else:
            tree._selected(tree._native_by_key['child2'], True, 'child2')
        assert tree.currentKey() == 'child2'
        native = dict(tree._native_by_key)
        parent.setText('updated parent')
        children[2].setText('updated child')
        children[1].setEnabled(False)
        pump()
        assert tree._native_by_key == native
        assert tree.isExpanded('parent')
        assert bool(runtime.backend.get_value(native['parent']))
        assert runtime.backend.get_item_configuration(native['child2'])['label'] == 'updated child'
        assert not runtime.backend.get_item_configuration(native['child1'])['enabled']
        assert tree.currentKey() == 'child2'
        if pointer:
            click('parent')
            assert tree.currentKey() == 'parent', 'Native branch handler identity was not accepted'
            assert tree.isExpanded('parent') == bool(runtime.backend.get_value(native['parent']))
            if not tree.isExpanded('parent'):
                click('parent')
                assert tree.isExpanded('parent')
        else:
            handler = tree._selection_handler_by_key['parent']
            runtime.backend.get_item_configuration(handler)['callback'](handler, None, 'parent')
            assert tree.currentKey() == 'parent'
        model.layoutChanged.emit()
        pump()
        tree._selected(native['child2'], True, 'child2')
        assert tree.currentKey() == 'parent'
        print('PASS: native tree label/enabled updates, stable node IDs/current/expansion, '
              'fresh branch handlers and stale callback rejection', flush=True)
    finally:
        if pointer:
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            user32.SetCursorPos(cursor.x, cursor.y)
        if window is not None: window.delete()
        if model is not None: model.delete()
        application.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
