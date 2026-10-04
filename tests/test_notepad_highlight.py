from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from WinUx.services.server_notepad_highlight import ServerNotepadHighlighter, compiled_patterns


def fixture(language="Python", sample="for i in range(10): # note\n    print('text')\n"):
    text = Mock()
    text.index.side_effect = lambda value: "100.0" if value == "@0,0" else "130.0"
    text.winfo_height.return_value = 400
    text.get.return_value = sample
    doc = SimpleNamespace(text=text, loaded=True, language=language, highlight_after=None,
                          highlight_generation=0, highlight_snapshot=None,
                          index_generation=0, performance_mode=False)
    root = Mock()
    root.after.side_effect = lambda delay, callback: callback
    highlighter = ServerNotepadHighlighter(SimpleNamespace(root=root))
    return highlighter, doc, root


class HighlightTests(unittest.TestCase):
    def test_identical_viewport_skips_native_tag_rewrites(self):
        highlighter, doc, _ = fixture()
        highlighter._highlight_document(doc)
        self.assertGreater(doc.text.tag_add.call_count, 0)
        doc.text.reset_mock()
        highlighter._highlight_document(doc)
        doc.text.tag_add.assert_not_called()
        doc.text.tag_remove.assert_not_called()

    def test_reload_revision_and_sample_changes_invalidate_snapshot(self):
        highlighter, doc, _ = fixture()
        highlighter._highlight_document(doc)
        for change in (lambda: setattr(doc, "index_generation", 1),
                       lambda: setattr(doc, "language", "JSON"),
                       lambda: setattr(doc.text.get, "return_value", '{"x": 5}')):
            doc.text.reset_mock()
            change()
            highlighter._highlight_document(doc)
            self.assertEqual(doc.text.tag_remove.call_count, 7)

    def test_style_configuration_invalidates_snapshot(self):
        highlighter, doc, _ = fixture()
        highlighter._highlight_document(doc)
        highlighter._configure_syntax_tags(doc)
        self.assertIsNone(doc.highlight_snapshot)
        self.assertEqual(doc.text.tag_configure.call_count, 8)

    def test_large_viewport_is_not_retained_in_cache(self):
        highlighter, doc, _ = fixture(sample="x" * 200001)
        highlighter._highlight_document(doc)
        self.assertIsNone(doc.highlight_snapshot)

    def test_old_debounce_callback_is_invalidated_even_when_cancel_fails(self):
        highlighter, doc, root = fixture()
        highlighter._highlight_document = Mock()
        highlighter._schedule_highlight(doc)
        old = doc.highlight_after
        root.after_cancel.side_effect = RuntimeError("already delivered")
        highlighter._schedule_highlight(doc, immediate=True)
        current = doc.highlight_after
        old()
        highlighter._highlight_document.assert_not_called()
        current()
        highlighter._highlight_document.assert_called_once_with(doc)

    def test_all_existing_language_rules_compile_and_match(self):
        cases = {"Python": "def x(): # note", "Abaqus INP": "*NODE\n1, 2, 3",
                 "JSON": '{"x": true}', "XML/HTML": '<tag a="b">', "C/C++": "int x = 3;",
                 "Fortran": "INTEGER X ! note", "Shell": "export X=$VALUE", "YAML": "name: true"}
        for language, sample in cases.items():
            with self.subTest(language=language):
                patterns = compiled_patterns(language)
                self.assertIs(patterns, compiled_patterns(language))
                self.assertTrue(any(list(pattern.finditer(sample)) for pattern, _ in patterns))
        self.assertEqual(compiled_patterns("Normal Text"), ())

    def test_unloaded_document_does_not_schedule_or_scan(self):
        highlighter, doc, root = fixture()
        doc.loaded = False
        highlighter._schedule_highlight(doc)
        highlighter._highlight_document(doc)
        root.after.assert_not_called()
        doc.text.get.assert_not_called()
