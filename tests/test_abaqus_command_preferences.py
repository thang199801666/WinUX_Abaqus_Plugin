"""Regression coverage for preferred Abaqus launcher selection."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from WinUx.preferences.abaqus_versions import AbaqusVersionPreferences


class AbaqusCommandPreferenceTests(unittest.TestCase):
    def test_new_profile_defaults_to_abq2026(self):
        with TemporaryDirectory() as root:
            prefs = AbaqusVersionPreferences(root=root)
            settings = prefs.load_settings()
            self.assertEqual(settings["default_command"], "abq2026")
            self.assertEqual(settings["versions"][0], "abq2026")
            self.assertIn("abq2023", settings["versions"])
            self.assertEqual(settings["versions"][-1], "abaqus")

    def test_saved_default_is_first_in_fallback_order(self):
        with TemporaryDirectory() as root:
            prefs = AbaqusVersionPreferences(root=root)
            prefs.save(["abq2026", "abq2023", "abaqus"], "abq2023")
            ordered = prefs.ordered_commands()
            self.assertEqual(ordered[0], "abq2023")
            self.assertIn("abq2026", ordered)
            self.assertIn("abaqus", ordered)

    def test_old_versions_only_profile_migrates_without_breaking(self):
        with TemporaryDirectory() as root:
            prefs = AbaqusVersionPreferences(root=root)
            prefs._store.save({"versions": ["abq2023", "abaqus"]})
            settings = prefs.load_settings()
            self.assertEqual(settings["default_command"], "abq2026")
            self.assertEqual(settings["versions"][0], "abq2026")
            self.assertIn("abq2023", settings["versions"])
            self.assertIn("abaqus", settings["versions"])


if __name__ == "__main__":
    unittest.main()
