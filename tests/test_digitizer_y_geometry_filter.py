import unittest

from WinUx.plotdigitizer.core.ticks.recognition import _label_supported_major_mark_subset


class YGeometryFilterTests(unittest.TestCase):
    def test_complete_regular_label_row_prunes_unlabelled_curve_crossings(self):
        true = [96.5, 126.5, 156.5, 186.5, 216.0, 246.0, 274.5]
        candidates = [(p, 8.0) for p in true]
        candidates += [(222.0, 8.0), (234.4, 7.0), (256.9, .4)]
        selected = _label_supported_major_mark_subset(candidates, true)
        self.assertEqual(len(true), len(selected))
        self.assertEqual(true, [round(p, 1) for p, _ in selected])

    def test_missing_endpoint_label_does_not_prune_a_real_endpoint_tick(self):
        candidates = [(150 + 70 * i, 8.0) for i in range(9)]
        # Simulates rotated/clipped text where the bottom endpoint label is
        # missing but its physical tick remains visible.
        protected = [150 + 70 * i for i in range(8)]
        selected = _label_supported_major_mark_subset(candidates, protected)
        self.assertEqual(candidates, selected)


if __name__ == '__main__':
    unittest.main()
