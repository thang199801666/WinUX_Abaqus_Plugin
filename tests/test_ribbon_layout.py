import unittest
from DearUIQt.ribbon.layout import RibbonLayoutEngine


class RibbonLayoutTests(unittest.TestCase):
    def setUp(self):
        self.engine = RibbonLayoutEngine(separator_width=7, gap=2, overflow_width=65, padding=10)
        self.groups = [('selection', 220), ('data', 140), ('charts', 180)]

    def test_all_fit(self):
        plan = self.engine.allocate(self.groups, 600)
        self.assertEqual(plan.visible, ('selection', 'data', 'charts'))
        self.assertFalse(plan.overflow)

    def test_overflow_preserves_order(self):
        plan = self.engine.allocate(self.groups, 400)
        self.assertEqual(plan.visible, ('selection',))
        self.assertEqual(plan.overflow, ('data', 'charts'))
        self.assertLessEqual(plan.required_width, 390)

    def test_narrow_keeps_overflow_access(self):
        plan = self.engine.allocate(self.groups, 70)
        self.assertEqual(plan.visible, ())
        self.assertEqual(plan.overflow, ('selection', 'data', 'charts'))

    def test_empty(self):
        self.assertFalse(self.engine.allocate([], 200).overflow)


if __name__ == '__main__':
    unittest.main()


class RibbonAdaptiveLayoutTests(unittest.TestCase):
    def setUp(self):
        self.engine = RibbonLayoutEngine(separator_width=7, gap=2, overflow_width=65, padding=10)
        self.groups = [('selection', 220), ('data', 140), ('charts', 180)]

    def test_adaptive_keeps_all_groups_by_reducing_before_overflow(self):
        plan = self.engine.allocate_adaptive(self.groups, 500)
        self.assertFalse(plan.overflow)
        self.assertEqual(plan.visible, ('selection', 'data', 'charts'))
        self.assertIn(plan.state_for('charts'), ('medium', 'small'))
        self.assertLess(plan.width_for('charts'), 180)

    def test_adaptive_progresses_large_medium_small_collapsed(self):
        wide = self.engine.allocate_adaptive(self.groups, 700)
        medium = self.engine.allocate_adaptive(self.groups, 500)
        narrow = self.engine.allocate_adaptive(self.groups, 250)
        self.assertTrue(all(group.state == 'large' for group in wide.groups))
        self.assertTrue(any(group.state in ('medium', 'small') for group in medium.groups))
        self.assertTrue(narrow.overflow)
        self.assertEqual(narrow.state_for(narrow.overflow[-1]), 'collapsed')

    def test_adaptive_state_lookup(self):
        plan = self.engine.allocate_adaptive(self.groups, 390)
        self.assertIn(plan.state_for('selection'), ('large', 'medium', 'small', 'collapsed'))
        self.assertIsNone(plan.state_for('missing'))
        self.assertIsNone(plan.width_for('missing'))

    def test_adaptive_rejects_invalid_scale_order(self):
        with self.assertRaises(ValueError):
            self.engine.allocate_adaptive(self.groups, 400, medium_scale=0.5, small_scale=0.8)
