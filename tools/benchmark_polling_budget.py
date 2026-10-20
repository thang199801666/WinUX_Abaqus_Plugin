"""Deterministic virtual-time server query counts; no live SSH required."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.services.adaptive_polling import AdaptivePollingPolicy
from WinUx.services.polling_budget import CostAwarePollingPolicy


class PreviousCostAwarePollingPolicy(CostAwarePollingPolicy):
    """Freeze the previous formula so comparisons are reproducible."""

    def next_query_delay(self, now=None):
        return 0.0

    def record_query_start(self, now=None):
        pass

    def observe(self, signature, now=None):
        now = self._clock() if now is None else float(now)
        changed = not self._has_signature or signature != self._signature
        baseline = AdaptivePollingPolicy.observe(self, signature, now=now)
        interactive, self._interactive = self._interactive, False
        recovering = now < self._fast_until
        if changed or interactive or recovering:
            if recovering:
                self._stable_samples = 0
                self._last_change_at = now
            self._current_interval = self.min_interval
        else:
            cost_delay = (self.query_seconds or 0.0) * (1.0 / self.target_duty - 1.0)
            self._current_interval = self._spread(max(baseline, cost_delay))
        return self.current_interval


def simulate(policy_class, query_seconds, seconds=300,
             state_changes_every=None, continuous_refresh=False):
    now = [0.0]
    options = {"jitter": 0} if issubclass(policy_class, CostAwarePollingPolicy) else {}
    policy = policy_class(5, 30, clock=lambda: now[0], **options)
    count = 0
    while now[0] < seconds:
        if isinstance(policy, CostAwarePollingPolicy):
            if continuous_refresh:
                policy.hold_fast(30)
            now[0] += policy.next_query_delay()
            if now[0] >= seconds:
                break
            policy.record_query_start()
        now[0] += query_seconds
        if isinstance(policy, CostAwarePollingPolicy):
            policy.record_cost(query_seconds)
        signature = int(now[0] / state_changes_every) if state_changes_every else "unchanged"
        previous_changes = policy.change_count
        delay = policy.observe(signature)
        if policy.change_count != previous_changes:
            if policy_class is PreviousCostAwarePollingPolicy:
                delay = policy.hold_fast(30)
            elif isinstance(policy, CostAwarePollingPolicy):
                delay = policy.force_fast()
        count += 1
        now[0] += 0 if continuous_refresh else delay
    return count


def main():
    report = {}
    scenarios = (
        ("fast_quiet_server", 0.1, {}),
        ("slow_quiet_server", 4.0, {}),
        ("job_state_change_every_40_seconds", 0.1, {"state_changes_every": 40}),
        ("continuous_refresh_requests", 0.1, {"continuous_refresh": True}),
    )
    for name, cost, options in scenarios:
        previous = simulate(PreviousCostAwarePollingPolicy, cost, **options)
        improved = simulate(CostAwarePollingPolicy, cost, **options)
        report[name] = {
            "virtual_seconds": 300,
            "query_cost_seconds": cost,
            "previous_query_count": previous,
            "improved_query_count": improved,
            "query_reduction_percent": round(100.0 * (previous - improved) / previous, 1),
        }
    output = json.dumps(report, indent=2)
    Path(__file__).with_name("polling_budget_results.json").write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
