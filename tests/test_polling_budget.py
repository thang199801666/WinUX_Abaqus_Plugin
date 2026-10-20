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

    def test_recovery_keeps_unchanged_snapshots_fast_until_scheduler_settles(self):
        policy = self.policy()
        policy.record_cost(100)
        policy.observe("job-running", now=0)
        self.assertEqual(policy.observe("job-running", now=60), 30)
        policy.hold_fast(30, now=60)
        for now in (60, 65, 70, 75, 80, 85):
            self.assertEqual(policy.observe("job-running", now=now), 5)
        self.assertEqual(policy.observe("job-removed", now=87), 5)
        self.assertEqual(policy.snapshot(now=87)["fast_recovery_seconds"], 3)
        self.assertEqual(policy.observe("job-removed", now=91), 30)

    def test_second_action_extends_recovery_without_shortening_existing_window(self):
        policy = self.policy()
        policy.record_cost(100)
        policy.observe("stable", now=0)
        policy.hold_fast(30, now=0)
        policy.hold_fast(30, now=20)
        policy.hold_fast(1, now=21)
        self.assertEqual(policy.observe("stable", now=45), 5)
        self.assertEqual(policy.observe("stable", now=51), 30)

    def test_recovery_does_not_disable_error_backoff(self):
        policy = self.policy()
        policy.hold_fast(30, now=0)
        self.assertGreater(policy.on_error(), 5)
        self.assertEqual(policy.observe("reconnected", now=5), 5)

    def test_refresh_budget_allows_one_follow_up_then_limits_repeated_requests(self):
        policy = self.policy()
        for _ in range(2):
            self.assertEqual(policy.next_query_delay(now=0), 0)
            policy.record_query_start(now=0)
        for _ in range(1000):
            policy.force_fast(now=0)
            self.assertEqual(policy.next_query_delay(now=0), 5)
        self.assertEqual(policy.next_query_delay(now=2), 3)
        self.assertEqual(policy.next_query_delay(now=5), 0)
        policy.record_query_start(now=5)
        self.assertEqual(policy.next_query_delay(now=5), 5)

    def test_normal_poll_intervals_do_not_pay_an_extra_budget_delay(self):
        policy = self.policy()
        for now in range(0, 100, 5):
            self.assertEqual(policy.next_query_delay(now=now), 0)
            policy.record_query_start(now=now)

    def test_stable_sample_limit_can_back_off_without_waiting_for_quiet_time(self):
        policy = self.policy()
        policy.observe("stable", now=0)
        for now in range(1, 9):
            policy.observe("stable", now=now)
        self.assertEqual(policy.current_interval, 30)

    def test_quiet_time_limit_can_back_off_without_many_samples(self):
        policy = self.policy()
        policy.observe("stable", now=0)
        self.assertEqual(policy.observe("stable", now=90), 30)

    def test_negative_jitter_cannot_violate_expensive_query_duty_budget(self):
        policy = CostAwarePollingPolicy(5, 30, clock=lambda: 0, random_source=lambda: 0)
        policy.record_cost(2)
        policy.observe("stable")
        self.assertGreaterEqual(policy.observe("stable"), 18)
