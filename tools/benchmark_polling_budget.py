"""Deterministic virtual-time server query counts; no live SSH required."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.services.adaptive_polling import AdaptivePollingPolicy
from WinUx.services.polling_budget import CostAwarePollingPolicy


def simulate(policy_class, query_seconds, seconds=300):
    now = [0.0]
    options = {"jitter": 0} if policy_class is CostAwarePollingPolicy else {}
    policy = policy_class(5, 30, clock=lambda: now[0], **options)
    count = 0
    while now[0] < seconds:
        now[0] += query_seconds
        if isinstance(policy, CostAwarePollingPolicy):
            policy.record_cost(query_seconds)
        delay = policy.observe("unchanged")
        count += 1
        now[0] += delay
    return count


def main():
    report = {}
    for name, cost in (("fast_quiet_server", 0.1), ("slow_quiet_server", 4.0)):
        report[name] = {
            "virtual_seconds": 300,
            "query_cost_seconds": cost,
            "previous_query_count": simulate(AdaptivePollingPolicy, cost),
            "cost_aware_query_count": simulate(CostAwarePollingPolicy, cost),
        }
    output = json.dumps(report, indent=2)
    Path(__file__).with_name("polling_budget_results.json").write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
