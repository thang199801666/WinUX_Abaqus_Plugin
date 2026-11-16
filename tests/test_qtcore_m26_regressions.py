import gc
import json
import os
import tempfile
import weakref

from DearUIQt.core.dispatcher import QEventDispatcher
from DearUIQt.core.concurrent import QThreadPool
from DearUIQt.runtime import QGuiRuntime


class Clock:
    def __init__(self):
        self.value = 0.0
    def __call__(self):
        return self.value
    def advance(self, seconds):
        self.value += float(seconds)


def test_sustained_starvation_requires_fraction_and_samples():
    clock = Clock()
    d = QEventDispatcher(clock=clock)
    for _ in range(6):
        d.post(lambda: None, priority=-1)
        clock.advance(0.060)
        d.processEvents(max_callbacks=None, time_budget_ms=None)
    snap = d.sustainedStarvationSnapshot(
        window_seconds=30, starvation_threshold_ms=50,
        min_samples=5, min_starvation_fraction=0.5)
    assert snap['ready'] is True
    assert snap['threshold_breached'] is True
    assert -1 in snap['sustained_priorities']


def test_callback_category_snapshot_is_string_only_and_bounded():
    clock = Clock()
    d = QEventDispatcher(clock=clock)
    class Owner:
        def callback(self):
            pass
    owner = Owner()
    ref = weakref.ref(owner)
    d.post(owner.callback)
    clock.advance(0.010)
    d.processEvents(max_callbacks=None, time_budget_ms=None)
    del owner
    gc.collect()
    assert ref() is None
    snap = d.callbackCategoryDiagnosticsSnapshot(window_seconds=30, category_depth=2)
    assert snap['sample_count'] == 1
    assert all(isinstance(k, str) for k in snap['categories'])


def test_named_pool_metadata_does_not_retain_owner():
    class Owner:
        pass
    owner = Owner()
    ref = weakref.ref(owner)
    pool = QThreadPool(maxThreadCount=1, name='m26-test', category='io', owner=owner)
    del owner
    gc.collect()
    assert ref() is None
    snap = pool.diagnosticsSnapshot()
    assert snap['category'] == 'io'
    assert snap['owner'].endswith('.Owner') or snap['owner'] == 'Owner'
    pool.close()


def test_performance_envelope_round_trip_is_explicit_io_only():
    runtime = QGuiRuntime(type("Backend", (), {})())
    dispatcher = QEventDispatcher()
    envelope = runtime.performanceEnvelopeSnapshot(dispatcher, window_seconds=30)
    assert envelope['schema'] == 2
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, 'baseline.json')
        saved = runtime.savePerformanceEnvelope(path, envelope)
        assert saved == os.path.abspath(path)
        loaded = runtime.loadPerformanceEnvelope(path)
        assert loaded == envelope
        comparison = runtime.comparePerformanceEnvelope(loaded, dispatcher, window_seconds=30)
        assert comparison['schema'] == 2
        json.dumps(comparison)
