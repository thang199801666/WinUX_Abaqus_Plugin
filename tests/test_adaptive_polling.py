"""Regression coverage for adaptive qstat and live ODB polling."""

from pathlib import Path
import tempfile

from WinUx.preferences.performance import PerformancePreferences
from WinUx.services.adaptive_polling import AdaptivePollingPolicy, EventIntervalLearner
from WinUx.services.odb_history_live import build_remote_odb_history_live_script


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


def test_adaptive_policy_starts_fast_backs_off_and_resets_on_change():
    clock = Clock()
    policy = AdaptivePollingPolicy(5, 30, 4, 40, clock=clock)
    assert policy.observe(("job", "Q")) == 5

    intervals = []
    for _ in range(4):
        clock.advance(10)
        intervals.append(policy.observe(("job", "Q")))
    assert intervals == sorted(intervals)
    assert intervals[-1] == 30
    assert policy.poll_count == 5

    clock.advance(1)
    assert policy.observe(("job", "R")) == 5
    assert policy.change_count == 1
    assert policy.stable_samples == 0


def test_performance_preferences_validate_min_max_and_defaults():
    with tempfile.TemporaryDirectory() as root:
        prefs = PerformancePreferences(root=root)
        defaults = prefs.load()
        assert defaults["qstat_min_interval"] == 5.0
        assert defaults["qstat_max_interval"] == 30.0
        assert defaults["odb_min_interval"] == 1.0
        assert defaults["odb_max_interval"] == 60.0
        assert defaults["odb_quiet_seconds_to_max"] == 180.0
        assert defaults["odb_history_alpha"] == 0.35
        assert defaults["odb_prediction_fraction"] == 0.25
        assert defaults["odb_history_confidence_samples"] == 3

        saved = prefs.save({
            "qstat_min_interval": 12,
            "qstat_max_interval": 3,
            "odb_min_interval": 2,
            "odb_max_interval": 1,
        })
        assert saved["qstat_max_interval"] == 12.0
        assert saved["odb_max_interval"] == 2.0


def test_remote_odb_monitor_skips_heavy_read_when_file_is_unchanged():
    script = build_remote_odb_history_live_script()
    assert "def _file_fingerprint(path):" in script
    assert "os.stat(path)" in script
    assert "if not file_changed and not force_refresh:" in script
    assert 'command.get("cmd") == "config"' in script
    assert "def _learn_event(self, now):" in script
    assert "learned_interval" in script
    assert 'command.get("historyAlpha"' in script
    assert "if file_changed:" in script
    compile(script, "remote_live_odb.py", "exec")



def test_event_interval_learner_uses_history_without_overtrusting_first_sample():
    learner = EventIntervalLearner(alpha=0.5, prediction_fraction=0.25, confidence_samples=3)
    baseline = 5.0
    assert learner.recommend(10, baseline, 1, 60) == baseline

    learner.observe_interval(120)
    first = learner.recommend(0, baseline, 1, 60)
    assert baseline < first < 60
    assert learner.samples == 1

    learner.observe_interval(126)
    learner.observe_interval(118)
    mature = learner.recommend(0, baseline, 1, 60)
    assert mature > first
    assert mature <= 60
    assert learner.confidence == 1.0

    near_due = learner.recommend(115, 45, 1, 60)
    assert near_due < 45


def test_odb_controller_learns_appearance_waits_in_the_session():
    root = Path(__file__).resolve().parents[1] / "WinUx"
    facade = (root / "controller.py").read_text(encoding="utf-8")
    source = (root / "controllers" / "job_plot.py").read_text(encoding="utf-8")
    assert "self._job_plots = JobPlotController(self)" in facade
    assert "self._appearance_learner = EventIntervalLearner()" in source
    assert "def remember_appearance_wait" in source
    assert "def discovery_delay" in source
    assert "self._appearance_learner.observe_interval(seconds)" in source

def test_qstat_polling_uses_meaningful_signature_and_performance_settings():
    root = Path(__file__).resolve().parents[1] / "WinUx"
    facade = (root / "controller.py").read_text(encoding="utf-8")
    source = (root / "controllers" / "job_polling.py").read_text(encoding="utf-8")
    assert "self._job_polling = JobPollingController(self, adopt_existing=True)" in facade
    assert "job.elapsed" not in source
    assert "PerformancePreferences().load()" in source
    assert "policy.observe(self.signature(jobs))" in source
    assert "self.app._job_poll_wakeup" in source
