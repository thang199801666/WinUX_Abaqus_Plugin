"""Tests for declarative ribbon presets without a graphical backend."""
import unittest

from DearUIQt.ribbon import (
    RibbonTab,
    RibbonTemplateFactory,
    RibbonTemplate,
    RibbonTabTemplate,
    RibbonGroupTemplate,
    RibbonCommandTemplate,
    apply_ribbon_template,
    get_ribbon_template,
    ribbon_template_names,
)


class FakeBar:
    def __init__(self):
        self.calls = []
        self.responsive = None

    def create_tab(self, key, label, *, activate=None):
        self.calls.append(("create_tab", key, label, activate))
        return RibbonTab(self, key, "tab:" + key)

    def set_responsive(self, enabled=True, *, width=None):
        self.responsive = (enabled, width)
        return {}

    def __getattr__(self, method):
        def record(*args, **kwargs):
            self.calls.append((method, args, kwargs))
            if method.startswith(("set_", "is_")):
                return True
            return "{}:{}".format(method, len(self.calls))
        return record


class RibbonTemplateTests(unittest.TestCase):
    def test_builtin_catalog(self):
        names = ribbon_template_names()
        self.assertIn("office-data", names)
        self.assertIn("document", names)
        self.assertIn("data-analysis", names)
        self.assertIn("plot-workbench", names)
        office = get_ribbon_template("office-data")
        self.assertEqual(
            [tab.text for tab in office.tabs],
            ["Home", "Data Manipulation", "Insert", "Appearance", "Export"],
        )
        home = office.tabs[0]
        self.assertEqual(
            [group.text for group in home.groups],
            ["Selection", "Data", "Page Layout", "Tables", "Charts", "Zoom", "More", "Search"],
        )

    def test_apply_custom_template_and_bindings(self):
        called = []
        template = RibbonTemplate(
            "test-template", "Test", tabs=(
                RibbonTabTemplate("home", "Home", activate=True, groups=(
                    RibbonGroupTemplate("tools", "Tools", width=180, layout="small", commands=(
                        RibbonCommandTemplate("run", "Run", action="do_run", size="small"),
                        RibbonCommandTemplate("options", "Options", kind="menu", menu="options_menu"),
                        RibbonCommandTemplate("sep", kind="separator"),
                    )),
                )),
            ),
        )
        bar = FakeBar()
        instance = apply_ribbon_template(
            bar,
            template,
            actions={"do_run": lambda: called.append("run")},
            menus={"options_menu": [{"label": "A"}]},
            images={"run": "run.png"},
            responsive_width=800,
        )
        self.assertEqual(tuple(instance.tabs), ("home",))
        self.assertIn(("home", "tools"), instance.groups)
        self.assertIn("run", instance.commands)
        self.assertIn("options", instance.commands)
        self.assertEqual(len(instance.separators), 1)
        self.assertEqual(bar.responsive, (True, 800))
        add_run = next(row for row in bar.calls if row[0] == "add_button")
        self.assertEqual(add_run[1][:4], ("home", "tools", "run", "Run"))
        self.assertEqual(add_run[2]["image"], "run.png")

    def test_disable_unbound(self):
        template = RibbonTemplate(
            "disable-test", "Disable", tabs=(
                RibbonTabTemplate("home", "Home", groups=(
                    RibbonGroupTemplate("g", "G", commands=(
                        RibbonCommandTemplate("x", "X"),
                    )),
                )),
            ), responsive=False,
        )
        bar = FakeBar()
        apply_ribbon_template(bar, template, disable_unbound=True)
        call = next(row for row in bar.calls if row[0] == "add_button")
        self.assertFalse(call[2]["enabled"])
        self.assertIsNone(bar.responsive)


    def test_duplicate_command_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            RibbonTemplate(
                "duplicates", "Duplicates", tabs=(
                    RibbonTabTemplate("a", "A", groups=(
                        RibbonGroupTemplate("g1", "G1", commands=(RibbonCommandTemplate("same", "One"),)),
                    )),
                    RibbonTabTemplate("b", "B", groups=(
                        RibbonGroupTemplate("g2", "G2", commands=(RibbonCommandTemplate("same", "Two"),)),
                    )),
                ),
            )

    def test_factory_reads_same_registry(self):
        self.assertIs(RibbonTemplateFactory.get("plot-workbench"), get_ribbon_template("plot-workbench"))


if __name__ == "__main__":
    unittest.main()
