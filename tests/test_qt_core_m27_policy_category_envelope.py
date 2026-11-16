import gc
import json
import weakref

from DearUIQt.core import QEventDispatcher, QPerformancePolicy, QThreadPool
from DearUIQt.runtime import QGuiRuntime
from WinUx.runtime.ui_dispatcher import UiDispatcher


class Clock:
    def __init__(self):
        self.now = 0.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += float(seconds)


def _callback(module, qualname):
    def callback():
        return None
    callback.__module__ = module
    callback.__qualname__ = qualname
    return callback


def _deliver(dispatcher, clock, callback, wait_ms, count):
    for _ in range(count):
        dispatcher.post(callback)
        clock.advance(float(wait_ms) / 1000.0)
        dispatcher.processEvents(max_callbacks=None, time_budget_ms=None)


def test_typed_performance_policy_round_trips_mapping():
    policy = QPerformancePolicy(max_idle_render_rate_hz=1.25, min_dispatcher_samples=9)
    copy = QPerformancePolicy.fromMapping(policy.toDict())
    assert copy == policy
    assert copy.max_idle_render_rate_hz == 1.25
    assert copy.min_dispatcher_samples == 9


def test_callback_category_recent_vs_baseline_regression_is_non_overlapping():
    clock = Clock()
    dispatcher = QEventDispatcher(clock=clock)
    callback = _callback('winux.jobs.polling', 'JobPoller.tick')
    _deliver(dispatcher, clock, callback, wait_ms=1.0, count=8)
    clock.advance(6.0)
    _deliver(dispatcher, clock, callback, wait_ms=60.0, count=3)
    snap = dispatcher.callbackCategoryRegressionSnapshot(
        current_window_seconds=5.0,
        baseline_window_seconds=30.0,
        min_current_samples=3,
        min_baseline_samples=8,
        category_depth=2,
        max_p95_ratio=2.0,
        max_p95_delta_ms=20.0,
        max_callback_p95_delta_ms=100.0,
    )
    row = snap['comparison']['categories']['winux.jobs']
    assert row['ready'] is True
    assert row['current_sample_count'] == 3
    assert row['baseline_sample_count'] == 8
    assert snap['threshold_breached'] is True
    assert snap['breached_categories'] == ['winux.jobs']


def test_ui_dispatcher_forwards_category_regression_contract():
    dispatcher = UiDispatcher()
    assert callable(dispatcher.callbackCategoryComparisonSnapshot)
    assert callable(dispatcher.callbackCategoryRegressionSnapshot)
    dispatcher.close()


def test_task_lane_helper_uses_bounded_metadata_without_owner_retention():
    class Owner:
        pass
    owner = Owner()
    owner_ref = weakref.ref(owner)
    pool = QThreadPool.taskLane(
        'm27-lane', category='tests.m27', owner=owner,
        maxThreadCount=1, maxPending=2)
    meta = pool.diagnosticMetadata()
    assert meta['name'] == 'm27-lane'
    assert meta['category'] == 'tests.m27'
    assert meta['owner'].endswith('.Owner')
    del owner
    gc.collect()
    assert owner_ref() is None
    pool.close(wait=True)


def test_schema1_performance_envelope_migrates_to_schema2_with_policy(tmp_path):
    legacy = {
        'schema': 1,
        'window_seconds': 30.0,
        'frame': {'render_rate_hz': 0.5},
        'dispatcher': {'queue_wait_ms_p95': 2.0},
        'async_runtime': None,
    }
    path = tmp_path / 'legacy.json'
    path.write_text(json.dumps(legacy), encoding='utf-8')
    migrated = QGuiRuntime.loadPerformanceEnvelope(path)
    assert migrated['schema'] == 2
    assert migrated['policy']['max_idle_render_rate_hz'] == QPerformancePolicy().max_idle_render_rate_hz
    assert migrated['frame'] == legacy['frame']


def test_performance_acceptance_uses_shared_policy_object():
    runtime = object.__new__(QGuiRuntime)
    runtime.framePerformanceSnapshot = lambda: {
        'render_rate_hz_5s': 1.5,
        'idle_fraction_5s': 0.90,
    }
    policy = QPerformancePolicy(max_idle_render_rate_hz=1.0)
    snap = QGuiRuntime.performanceAcceptanceSnapshot(runtime, None, policy=policy)
    assert snap['ready'] is True
    assert snap['accepted'] is False
    assert snap['checks']['idle_render_rate_hz'] is False
    assert snap['policy']['max_idle_render_rate_hz'] == 1.0

def test_persisted_envelope_ci_acceptance_uses_policy_thresholds():
    runtime = object.__new__(QGuiRuntime)
    runtime.performanceEnvelopeSnapshot = lambda dispatcher=None, window_seconds=30.0, policy=None: {
        'schema': 2,
        'window_seconds': window_seconds,
        'policy': QPerformancePolicy.fromMapping(policy).toDict(),
        'frame': {'render_rate_hz': 2.0, 'idle_fraction': 0.80, 'wait_p95_ms': 10.0},
        'dispatcher': {'callback_sample_count': 10, 'queue_wait_ms_p95': 30.0,
                       'callback_duration_ms_p95': 10.0, 'turn_duration_ms_p95': 12.0},
        'async_runtime': None,
    }
    baseline = {
        'schema': 2,
        'window_seconds': 30.0,
        'policy': QPerformancePolicy().toDict(),
        'frame': {'render_rate_hz': 1.0, 'idle_fraction': 0.95, 'wait_p95_ms': 5.0},
        'dispatcher': {'callback_sample_count': 20, 'queue_wait_ms_p95': 10.0,
                       'callback_duration_ms_p95': 5.0, 'turn_duration_ms_p95': 6.0},
        'async_runtime': None,
    }
    policy = QPerformancePolicy(max_render_rate_ratio=1.5,
                                max_queue_wait_p95_ratio=2.0,
                                max_queue_wait_p95_delta_ms=15.0,
                                max_category_callback_p95_delta_ms=4.0,
                                min_current_samples=5, min_baseline_samples=5)
    snap = QGuiRuntime.performanceEnvelopeAcceptanceSnapshot(runtime, baseline, object(), policy=policy)
    assert snap['ready'] is True
    assert snap['accepted'] is False
    assert snap['checks']['render_rate_ratio'] is False
    assert snap['checks']['dispatcher_queue_wait_ratio'] is False
