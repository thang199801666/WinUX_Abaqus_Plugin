import threading

from DearUIQt.QtCore import QThreadPool


def test_qthreadpool_spawn_failure_completes_future_instead_of_hanging(monkeypatch):
    pool = QThreadPool(maxThreadCount=1, maxPending=4, name="spawn-failure")

    def fail_start(_thread):
        raise RuntimeError("thread quota exhausted")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    future = pool.start(lambda: 123)
    assert future.waitForFinished(0.2)
    assert isinstance(future.exception(), RuntimeError)
    assert "unable to start thread-pool worker" in str(future.exception())
    assert pool.queuedTaskCount() == 0
    assert pool.activeThreadCount() == 0
    pool.close()


def test_qthreadpool_try_start_returns_none_when_no_worker_can_spawn(monkeypatch):
    pool = QThreadPool(maxThreadCount=1, maxPending=4, name="try-spawn-failure")

    def fail_start(_thread):
        raise OSError("no thread resources")

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    assert pool.tryStart(lambda: 456) is None
    assert pool.queuedTaskCount() == 0
    pool.close()
