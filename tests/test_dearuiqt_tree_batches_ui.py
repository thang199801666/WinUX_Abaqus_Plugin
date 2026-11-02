"""Standalone tree batching/native identities; --pointer exercises mouse input."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.core import Qt
from DearUIQt.widgets import QApplication, QMainWindow
from DearUIQt.modelview import QTreeWidget, QTreeWidgetItem


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    application = QApplication(after=host.after)
    window = None
    cursor = wintypes.POINT()
    pointer = '--pointer' in sys.argv
    if pointer:
        ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor))
    try:
        window = QMainWindow('DearUIQt tree batch regression', width=500, height=360,
                             after=host.after, backend=runtime.backend)
        tree = QTreeWidget(parent=window, height=280, after=host.after)
        layouts = []
        tree.layoutChanged.connect(lambda: layouts.append(True))
        root = QTreeWidgetItem('root')
        with tree.batchUpdate():
            tree.addTopLevelItem(root)
            root.setExpanded(True)
            root.addChildren([QTreeWidgetItem('node ' + str(i)) for i in range(8)])
            root.child(1).setData(0, Qt.UserRole, 'shared')
            root.child(2).setData(0, Qt.UserRole, 'shared')
        assert len(layouts) == 1
        runtime.createViewport(title='DearUIQt tree batch regression', width=500, height=360)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        def pump(count=5):
            for _ in range(count):
                jobs = runtime.callbackQueue()
                if '--trace' in sys.argv:
                    for job in jobs:
                        print('CALLBACK', job, flush=True)
                runtime.backend.run_callbacks(jobs)
                host.pump()
                runtime.renderFrame()
                time.sleep(.01)
        pump(15)
        selected = root.child(2)
        if pointer:
            user32 = ctypes.windll.user32
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.FindWindowW.restype = wintypes.HWND
            hwnd = user32.FindWindowW(None, 'DearUIQt tree batch regression')
            assert hwnd
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
            pump(8)
            if '--trace' in sys.argv:
                print('STATES', [(tag, runtime.backend.get_item_state(tag)) for tag in
                                 (window.tag, tree.tag, tree.nativeRow(selected), tree.nativeItem(selected))], flush=True)
            pos = runtime.backend.get_item_rect_min(tree.nativeItem(selected))
            size = runtime.backend.get_item_rect_size(tree.nativeItem(selected))
            point = wintypes.POINT(int(pos[0] + 60), int(pos[1] + size[1] / 2))
            user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point))
            if '--trace' in sys.argv:
                print('POINTER', hwnd, (point.x, point.y), tree._item_by_overlay_handler, flush=True)
            user32.SetCursorPos(point.x, point.y)
            pump()
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
            pump(3)
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
            pump(8)
        else:
            handler = next(key for key, item in tree._item_by_overlay_handler.items() if item is selected)
            callback = runtime.backend.get_item_configuration(handler)['callback']
            callback(handler, None, 'shared')
        assert tree.currentItem() is selected
        if pointer:
            # The renderer toggles a selected Selectable off on the next press;
            # QTreeWidget single-selection semantics must restore it.
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            pump(3)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            pump(8)
            assert tree.currentItem() is selected
            assert bool(runtime.backend.get_value(tree.nativeItem(selected)))
        if pointer:
            # Exercise the decoration overlay's item handler as well as text.
            pos = runtime.backend.get_item_rect_min(tree.nativeItem(root))
            point = wintypes.POINT(int(pos[0] + 8), int(pos[1] + 10))
            user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point))
            user32.SetCursorPos(point.x, point.y)
            pump()
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            pump(3)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            pump(8)
            assert tree.currentItem() is root
            tree.setCurrentItem(selected)
        old = tree.nativeItem(selected)
        with tree.batchUpdate():
            root.child(0).setText(0, 'renamed')
            root.child(0).setHidden(True)
            tree.setIndentation(24)
        pump()
        assert len(layouts) == 2
        assert tree.nativeItem(selected) != old
        assert tree.currentItem() is selected
        assert bool(runtime.backend.get_value(tree.nativeItem(selected)))
        tree._native_clicked(old, True, root.child(1).data(0, Qt.UserRole))
        assert tree.currentItem() is selected
        root.setExpanded(False)
        pump()
        assert len(tree._rendered) == 1
        root.setExpanded(True)
        pump()
        assert tree.currentItem() is selected
        assert bool(runtime.backend.get_value(tree.nativeItem(selected)))
        print('PASS: standalone tree bulk layout, native click/selection, duplicate UserRole, '
              'batch refresh and collapse/expand restoration', flush=True)
    finally:
        if pointer:
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
            ctypes.windll.user32.SetCursorPos(cursor.x, cursor.y)
        if window is not None:
            window.delete()
        application.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
