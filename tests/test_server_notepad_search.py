from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from WinUx.services.server_notepad_search import ServerNotepadSearchController


class Var:
    def __init__(self, value=0, **kwargs):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


def fixture(content="One one"):
    text = Mock()
    text.get.return_value = content
    text.tag_ranges.return_value = ()
    text.index.side_effect = lambda value: "1.0" if value == "insert" else value
    doc = SimpleNamespace(path="/file.inp", text=text, loaded=True, last_find="",
                          last_find_options={})
    view = SimpleNamespace(
        _active_doc=lambda: doc, _documents={doc.path: doc}, _status_var=Var(),
        _find_vars={"find": Var("one"), "replace": Var("value"), "case": Var(False),
                    "regex": Var(False), "wrap": Var(True)},
        search_results=Mock(), search_results_panel=Mock(), notebook=Mock(), root=Mock(),
        after=Mock(), after_idle=Mock(), _show_find_replace=Mock(),
        _update_position=Mock(), _start_background_find_all=Mock(return_value=False),
    )
    return ServerNotepadSearchController(view, Mock()), view, doc


class SearchTests(unittest.TestCase):
    def test_replace_all_plain_case_insensitive_keeps_replacement_literal(self):
        controller, view, doc = fixture()
        view._find_vars["replace"].set(r"\1")
        controller._replace_all()
        doc.text.insert.assert_called_once_with("1.0", r"\1 \1")
        doc.text.edit_modified.assert_called_once_with(True)
        self.assertEqual(view._status_var.get(), "Replaced 2 occurrence(s)")

    def test_replace_all_regex_backreference_and_invalid_pattern(self):
        controller, view, doc = fixture("ab ab")
        view._find_vars["regex"].set(True)
        view._find_vars["find"].set("(a)b")
        view._find_vars["replace"].set(r"\1x")
        controller._replace_all()
        doc.text.insert.assert_called_once_with("1.0", "ax ax")
        doc.text.reset_mock()
        doc.text.get.return_value = "ab ab"
        view._find_vars["find"].set("[")
        controller._replace_all()
        doc.text.delete.assert_not_called()
        self.assertTrue(view._status_var.get().startswith("Regex error:"))

    def test_no_replacement_does_not_modify_document(self):
        controller, view, doc = fixture("nothing")
        controller._replace_all()
        doc.text.delete.assert_not_called()
        doc.text.insert.assert_not_called()
        self.assertEqual(view._status_var.get(), "No occurrences found")

    def test_find_previous_wraps_and_uses_matching_options(self):
        controller, view, doc = fixture()
        doc.text.search.side_effect = ["", "1.4"]
        with patch("WinUx.services.server_notepad_search.tk.IntVar", Var):
            self.assertTrue(controller._find_next(forward=False))
        calls = doc.text.search.call_args_list
        self.assertTrue(calls[0].kwargs["backwards"])
        self.assertTrue(calls[0].kwargs["nocase"])
        self.assertEqual(calls[1].args[1], "end-1c")
        doc.text.mark_set.assert_called_once_with("insert", "1.4")

    def test_closing_results_invalidates_generation(self):
        controller, view, _ = fixture()
        controller._search_state = {"generation": 0}
        controller._close_search_results()
        self.assertEqual(controller._search_generation, 1)
        self.assertIsNone(controller._search_state)
        view.search_results_panel.pack_forget.assert_called_once()

    def test_find_all_stale_generation_does_no_widget_work(self):
        controller, _, doc = fixture()
        controller._search_generation = 2
        controller._search_state = {"generation": 1}
        controller._find_all_step()
        doc.text.search.assert_not_called()

    def test_find_all_remains_bounded_and_resumes_after_slice(self):
        controller, view, doc = fixture()
        controller._search_state = {"generation": 0, "path": doc.path, "needle": "one",
                                    "index": "1.0", "count_var": Var(1), "matches": 0}
        doc.text.search.side_effect = ["1.0"] * 81 + [""]
        with patch("WinUx.services.server_notepad_search.time.perf_counter", return_value=0):
            controller._find_all_step()
            self.assertEqual(doc.text.search.call_count, 80)
            view.after.assert_called_once_with(1, controller._find_all_step)
            controller._find_all_step()
        self.assertIsNone(controller._search_state)
        self.assertEqual(len(controller._search_results_meta), 81)
        self.assertEqual(view._status_var.get(), "Find All: 81 match(es)")

    def test_find_all_uses_existing_background_index_first(self):
        controller, view, _ = fixture()
        view._start_background_find_all.return_value = True
        controller._find_all_current()
        view._start_background_find_all.assert_called_once()
        view.after_idle.assert_not_called()
