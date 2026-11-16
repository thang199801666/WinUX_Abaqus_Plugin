import json

import pytest

from DearUIQt.core import QEventDispatcher, QPerformancePolicy
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


def test_performance_policy_presets_are_immutable_independent_values():
    release = QPerformancePolicy.preset('release')
    interactive = QPerformancePolicy.preset('interactive')
    idle = QPerformancePolicy.preset('idle')
    assert QPerformancePolicy.presetNames() == ('interactive', 'idle', 'release')
    assert release == QPerformancePolicy()
    assert interactive.max_dispatcher_queue_wait_p95_ms < release.max_dispatcher_queue_wait_p95_ms
    assert idle.max_idle_render_rate_hz < release.max_idle_render_rate_hz
    assert QPerformancePolicy.fromMapping('idle') == idle
    overridden = QPerformancePolicy.preset('idle', max_idle_render_rate_hz=0.5)
    assert overridden.max_idle_render_rate_hz == 0.5
    assert idle.max_idle_render_rate_hz != overridden.max_idle_render_rate_hz
    with pytest.raises(ValueError):
        QPerformancePolicy.preset('unknown')


def test_category_sustained_regression_ranks_top_categories_for_watchdog():
    clock = Clock()
    dispatcher = QEventDispatcher(clock=clock)
    jobs = _callback('winux.jobs.polling', 'JobPoller.tick')
    plot = _callback('winux.plotdigitizer.detect', 'Detector.run')
    _deliver(dispatcher, clock, jobs, 1.0, 10)
    _deliver(dispatcher, clock, plot, 1.0, 10)
    clock.advance(20.0)
    _deliver(dispatcher, clock, jobs, 80.0, 8)
    _deliver(dispatcher, clock, plot, 45.0, 8)
    snap = dispatcher.callbackCategorySustainedRegressionSnapshot(
        current_window_seconds=15.0,
        baseline_window_seconds=60.0,
        min_current_samples=8,
        min_baseline_samples=10,
        max_p95_ratio=2.0,
        max_p95_delta_ms=20.0,
        max_callback_p95_delta_ms=100.0,
        top_limit=1,
    )
    assert snap['ready'] is True
    assert snap['threshold_breached'] is True
    assert snap['breached_category_count'] >= 1
    assert len(snap['top_regressed_categories']) == 1
    assert snap['top_regressed_categories'][0]['category'] == 'winux.jobs'


def test_ui_dispatcher_forwards_sustained_category_contract():
    dispatcher = UiDispatcher()
    assert callable(dispatcher.callbackCategorySustainedRegressionSnapshot)
    dispatcher.close()


def test_performance_report_exposes_category_sustained_watchdog_input():
    runtime = object.__new__(QGuiRuntime)
    runtime.performancePolicySnapshot = lambda policy=None: QPerformancePolicy.preset('release').toDict()
    runtime.framePerformanceSnapshot = lambda: {}
    runtime.framePerformanceRegressionSnapshot = lambda **kwargs: {}
    runtime.asyncRuntimeSnapshot = lambda: {}
    dispatcher = QEventDispatcher()
    snap = QGuiRuntime.performanceReportSnapshot(runtime, dispatcher)
    assert 'dispatcher_category_sustained_regression' in snap
    assert snap['dispatcher_category_sustained_regression']['threshold_breached'] is False


def test_future_schema_is_explicitly_rejected_without_downgrade():
    with pytest.raises(ValueError, match='cannot be downgraded'):
        QGuiRuntime.migratePerformanceEnvelope({'schema': 3, 'policy': {}})
    with pytest.raises(ValueError, match='minimum supported schema is 1'):
        QGuiRuntime.migratePerformanceEnvelope({'schema': 0})


def test_schema2_unknown_fields_round_trip_without_breaking_policy():
    envelope = {
        'schema': 2,
        'policy': QPerformancePolicy.preset('interactive').toDict(),
        'frame': {}, 'dispatcher': {}, 'async_runtime': None,
        'future_extension': {'opaque': True},
    }
    migrated = QGuiRuntime.migratePerformanceEnvelope(envelope)
    assert migrated['future_extension'] == {'opaque': True}
    assert migrated['policy']['max_dispatcher_queue_wait_p95_ms'] == 32.0


def test_server_notepad_dedicated_pool_uses_task_lane_metadata_source():
    source = open('WinUx/dialogs/server_notepad_dialog.py', 'r', encoding='utf-8').read()
    assert 'QThreadPool.taskLane(' in source
    assert 'category="server.notepad"' in source
    assert 'QThreadPool(maxThreadCount=6' not in source
