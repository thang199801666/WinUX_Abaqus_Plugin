import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

from DearUIQt.core import Qt, QSizePolicy
from DearUIQt.layouts.box import QLayoutItem
from DearUIQt.widgets.widget import QWidget


class SizePolicyTests(unittest.TestCase):
    def test_policy_values_and_flags_match_qt_shape(self):
        self.assertEqual(QSizePolicy.Fixed, 0)
        self.assertEqual(QSizePolicy.Minimum, QSizePolicy.GrowFlag)
        self.assertEqual(QSizePolicy.Maximum, QSizePolicy.ShrinkFlag)
        self.assertEqual(QSizePolicy.Preferred,
                         QSizePolicy.GrowFlag | QSizePolicy.ShrinkFlag)
        self.assertEqual(QSizePolicy.Expanding,
                         QSizePolicy.GrowFlag | QSizePolicy.ShrinkFlag | QSizePolicy.ExpandFlag)
        self.assertEqual(QSizePolicy.Ignored,
                         QSizePolicy.GrowFlag | QSizePolicy.ShrinkFlag | QSizePolicy.IgnoreFlag)

    def test_policy_is_compact_value_object_without_instance_dict(self):
        policy = QSizePolicy()
        self.assertFalse(hasattr(policy, '__dict__'))
        copied = policy.copy()
        self.assertEqual(copied, policy)
        self.assertIsNot(copied, policy)

    def test_stretch_clamps_to_qt_byte_range(self):
        policy = QSizePolicy()
        policy.setHorizontalStretch(-10)
        policy.setVerticalStretch(999)
        self.assertEqual(policy.horizontalStretch(), 0)
        self.assertEqual(policy.verticalStretch(), 255)

    def test_height_width_flags_and_control_type_survive_copy(self):
        policy = QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding,
                             QSizePolicy.LineEdit)
        policy.setHeightForWidth(True)
        policy.setWidthForHeight(False)
        policy.setRetainSizeWhenHidden(True)
        copied = policy.copy()
        self.assertTrue(copied.hasHeightForWidth())
        self.assertFalse(copied.hasWidthForHeight())
        self.assertTrue(copied.retainSizeWhenHidden())
        self.assertEqual(copied.controlType(), QSizePolicy.LineEdit)
        self.assertEqual(copied, policy)

    def test_transpose_swaps_axis_metadata_but_not_control_type_or_hidden_policy(self):
        policy = QSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding,
                             QSizePolicy.PushButton)
        policy.setHorizontalStretch(3)
        policy.setVerticalStretch(7)
        policy.setHeightForWidth(True)
        policy.setWidthForHeight(False)
        policy.setRetainSizeWhenHidden(True)

        transposed = policy.transposed()
        self.assertEqual(policy.horizontalPolicy(), QSizePolicy.Minimum)
        self.assertEqual(policy.verticalPolicy(), QSizePolicy.Expanding)
        self.assertEqual(transposed.horizontalPolicy(), QSizePolicy.Expanding)
        self.assertEqual(transposed.verticalPolicy(), QSizePolicy.Minimum)
        self.assertEqual(transposed.horizontalStretch(), 7)
        self.assertEqual(transposed.verticalStretch(), 3)
        self.assertFalse(transposed.hasHeightForWidth())
        self.assertTrue(transposed.hasWidthForHeight())
        self.assertTrue(transposed.retainSizeWhenHidden())
        self.assertEqual(transposed.controlType(), QSizePolicy.PushButton)

    def test_expanding_directions_follow_axis_policy(self):
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.assertEqual(policy.expandingDirections(), Qt.Horizontal)
        policy.setVerticalPolicy(QSizePolicy.MinimumExpanding)
        self.assertEqual(policy.expandingDirections(), Qt.Horizontal | Qt.Vertical)

    def test_widget_height_for_width_contract_uses_retained_policy(self):
        widget = object.__new__(QWidget)
        widget._size_policy = QSizePolicy()
        self.assertFalse(widget.hasHeightForWidth())
        self.assertEqual(widget.heightForWidth(100), -1)
        widget._size_policy.setHeightForWidth(True)
        self.assertTrue(widget.hasHeightForWidth())

    def test_layout_item_delegates_height_for_width_without_owning_widget(self):
        class Responsive:
            def hasHeightForWidth(self):
                return True
            def heightForWidth(self, width):
                return width // 2

        value = Responsive()
        item = QLayoutItem(value)
        self.assertFalse(hasattr(item, '__dict__'))
        self.assertTrue(item.hasHeightForWidth())
        self.assertEqual(item.heightForWidth(120), 60)

        class Plain:
            pass
        plain = QLayoutItem(Plain())
        self.assertFalse(plain.hasHeightForWidth())
        self.assertEqual(plain.heightForWidth(120), -1)
        self.assertFalse(plain.hasWidthForHeight())
        self.assertEqual(plain.widthForHeight(120), -1)

        class Reciprocal:
            def hasWidthForHeight(self):
                return True
            def widthForHeight(self, height):
                return height * 2

        reciprocal = QLayoutItem(Reciprocal())
        self.assertTrue(reciprocal.hasWidthForHeight())
        self.assertEqual(reciprocal.widthForHeight(25), 50)


if __name__ == '__main__':
    unittest.main(verbosity=2)
