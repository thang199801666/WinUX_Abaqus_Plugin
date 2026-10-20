import threading

from DearUIQt.runtime import StandaloneUiHost


def test_worker_callbacks_execute_on_ui_thread_in_order():
    host = StandaloneUiHost(None)
    observed = []
    ui_thread = threading.get_ident()

    def worker():
        for index in range(100):
            host.after(0, lambda i=index: observed.append((i, threading.get_ident())))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=5)
    assert not observed
    host.pump()
    assert observed == [(i, ui_thread) for i in range(100)]
