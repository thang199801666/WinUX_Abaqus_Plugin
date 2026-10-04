import unittest

from WinUx.services.polling_budget import CostAwarePollingPolicy


class PollingBudgetTests(unittest.TestCase):
    def policy(self, **kwargs):
        return CostAwarePollingPolicy(5, 30, clock=lambda: 0, jitter=0, **kwargs)

    def test_slow_quiet_query_respects_duty_budget(self):
        policy = self.policy()
        policy.record_cost(2)
        self.assertEqual(policy.observe("stable"), 5)
        self.assertEqual(policy.observe("stable"), 18)
        self.assertEqual(policy.snapshot()["query_seconds"], 2)

    def test_change_and_manual_refresh_bypass_cost_backoff(self):
        policy = self.policy()
        policy.record_cost(100)
        policy.observe("a")
        self.assertEqual(policy.observe("a"), 30)
        self.assertEqual(policy.observe("b"), 5)
        policy.force_fast()
        self.assertEqual(policy.observe("b"), 5)

    def test_ewma_dampens_one_slow_sample_and_recovers(self):
        policy = self.policy()
        policy.record_cost(1)
        policy.record_cost(9)
        self.assertEqual(policy.query_seconds, 3)
        for _ in range(20):
            policy.record_cost(0.1)
        self.assertLess(policy.query_seconds, 0.2)

    def test_jitter_and_errors_never_exceed_configured_bounds(self):
        for random_value in (0, 0.5, 1):
            policy = CostAwarePollingPolicy(5, 30, jitter=0.1, random_source=lambda: random_value)
            policy.record_cost(20)
            for _ in range(20):
                for delay in (policy.observe("a"), policy.on_error()):
                    self.assertGreaterEqual(delay, 5)
                    self.assertLessEqual(delay, 30)

