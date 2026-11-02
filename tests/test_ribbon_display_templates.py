"""Tests for generic ribbon appearance presets."""
import unittest

from DearUIQt.ribbon import (
    RibbonAdaptivePolicy,
    RibbonDisplayTemplate,
    RibbonDisplayTemplateFactory,
    get_ribbon_display_template,
    register_ribbon_display_template,
    ribbon_display_template_names,
)


class RibbonDisplayTemplateTests(unittest.TestCase):
    def test_builtin_catalog_is_visual_not_content_specific(self):
        names = ribbon_display_template_names()
        for key in ("classic", "balanced", "compact", "dense", "large-icons", "touch", "minimal"):
            self.assertIn(key, names)
        self.assertNotIn("plot-workbench", names)
        self.assertNotIn("office-data", names)

    def test_presets_have_meaningfully_different_geometry(self):
        compact = get_ribbon_display_template("compact")
        touch = get_ribbon_display_template("touch")
        self.assertLess(compact.body_height, touch.body_height)
        self.assertLess(compact.small_button_height, touch.small_button_height)
        self.assertLess(compact.large_icon_size, touch.large_icon_size)

    def test_metrics_are_ribbonbar_constant_overrides(self):
        dense = get_ribbon_display_template("dense")
        metrics = dense.metrics()
        self.assertEqual(metrics["BODY_HEIGHT"], dense.body_height)
        self.assertEqual(metrics["SMALL_ROWS"], dense.small_rows)
        self.assertEqual(metrics["BUTTON_ROUNDING"], dense.button_rounding)

    def test_custom_visual_template_can_be_registered(self):
        template = RibbonDisplayTemplate(
            key="unit-test-visual",
            name="Unit Test Visual",
            body_height=101,
            small_button_height=21,
        )
        register_ribbon_display_template(template, replace=True)
        self.assertIs(RibbonDisplayTemplateFactory.get("unit-test-visual"), template)

    def test_minimal_removes_group_chrome(self):
        minimal = get_ribbon_display_template("minimal")
        self.assertFalse(minimal.show_group_labels)
        self.assertFalse(minimal.show_group_separators)
        self.assertFalse(minimal.quick_access_default)


    def test_templates_own_generic_adaptive_policies(self):
        dense = get_ribbon_display_template("dense")
        large_icons = get_ribbon_display_template("large-icons")
        self.assertIsInstance(dense.adaptive_policy, RibbonAdaptivePolicy)
        self.assertGreater(dense.adaptive_policy.small_scale, large_icons.adaptive_policy.small_scale)

    def test_adaptive_policy_scales_geometry_without_content_names(self):
        policy = RibbonAdaptivePolicy(medium_scale=0.8, small_scale=0.6, medium_min_width=60, small_min_width=40)
        large, medium, small = policy.group_widths(200)
        self.assertEqual((large, medium, small), (200, 160, 120))
        self.assertLess(policy.command_width(100, "small"), policy.command_width(100, "medium"))


if __name__ == "__main__":
    unittest.main()
