"""Real DearUIQt widgets + standalone dispatcher; no WinUx imports/controller."""
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from DearUIQt import QGuiRuntime, StandaloneUiHost
from DearUIQt.core import QTimer, QMetaObject, Qt, QDebouncer
from DearUIQt.widgets import QApplication, QMainWindow, QLabel, QLineEdit


def main():
    runtime = QGuiRuntime()
    runtime.createContext(manual_callbacks=True)
    host = StandaloneUiHost(backend=runtime.backend)
    application = QApplication(after=host.after)
    window = None
    try:
        window = QMainWindow('DearUIQt dispatcher regression', width=480, height=280,
                             after=host.after, backend=runtime.backend)
        label = QLabel('initial', parent=window)
        runtime.createViewport(title='DearUIQt dispatcher regression', width=480, height=280)
        runtime.setup()
        runtime.setPrimaryWindow(window)
        runtime.show()
        timer = QTimer(window)
        ticks = []
        def timeout():
            ticks.append(threading.get_ident())
            label.setText('timer update')
            timer.stop()
        timer.timeout.connect(timeout)
        timer.start(10)
        deadline = time.monotonic() + 2
        while not ticks and time.monotonic() < deadline:
            host.pump()
            runtime.renderFrame()
        assert ticks == [threading.get_ident()]
        assert label.text() == 'timer update'
        assert not timer.isActive()

        wake = threading.Event()
        host.set_wake_callback(wake.set)
        worker = threading.Thread(target=lambda: label.setText('worker update'))
        worker.start()
        worker.join()
        assert wake.is_set(), 'Worker did not wake native-loop integration hook'
        assert label.text() == 'timer update', 'Worker mutated a native widget directly'
        host.pump()
        runtime.renderFrame()
        assert label.text() == 'worker update'
        timer.start(60000)
        timer.delete()
        for _ in range(4):
            host.pump()
            runtime.renderFrame()
        assert host.dispatcher.pendingCount() == 0
        once = QTimer.singleShot(0, lambda: label.setText('single shot'), context=label)
        host.pump()
        assert label.text() == 'single shot' and once._deleted
        temporary = QLabel('temporary context', parent=window)
        received = []
        cancelled = QTimer.singleShot(60000, lambda: received.append('stale'), context=temporary)
        temporary.delete()
        assert cancelled._deleted and host.dispatcher.pendingCount() == 0
        QMetaObject.invokeMethod(label, 'setText', Qt.QueuedConnection, 'queued method')
        host.pump()
        runtime.renderFrame()
        assert label.text() == 'queued method' and not received
        editor = QLineEdit('', parent=window)
        debounce = QDebouncer(label.setText, interval=0, parent=window)
        editor.textChanged.connect(debounce.trigger)
        for text in ('a', 'ab', 'abc'):
            editor.setText(text)
        assert label.text() == 'queued method'
        host.pump()
        assert label.text() == 'abc' and not debounce.isPending()
        editor.setText('cancelled')
        debounce.cancel()
        host.pump()
        assert label.text() == 'abc'
        print('PASS: DearUIQt-only window, QTimer/singleShot, context cleanup, '
              'queued methods, debounced editor, worker update and wake hook', flush=True)
    finally:
        if window is not None:
            window.delete()
        application.delete()
        host.close()
        runtime.destroy()


if __name__ == '__main__':
    main()
