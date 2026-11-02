"""Regex tester helpers used by Reference Chart Formula mode."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_winux
run_winux._configure_bundled_dependencies(str(ROOT))

from WinUx.dialogs.reference_chart_form import (
    RegexTesterDialog, ReferenceChartDialog, _RegexMatchOverlay,
    _first_regex_pattern, _regex_test_text, _regex_highlight_fragments,
    _regex_token_explanations, _format_regex_explanation,
    _format_regex_match_information, _format_regex_quick_reference,
    _format_regex_live_header, _format_regex_selected_match, _regex_line_column,
    _format_regex_elapsed, _regex_flag_letters, _regex_line_numbers,
    _format_regex_flag_explanation, _normalize_regex_replacement,
    _evaluate_regex_substitution, _parse_regex_unit_tests,
    _evaluate_regex_unit_tests, _format_regex_unit_test_results,
    _python_regex_code, _regex_debug_trace, _format_regex_debug_trace,
    _benchmark_regex, _format_regex_benchmark,
    _serialize_regex_session, _deserialize_regex_session,
    _evaluate_regex_extraction, _export_regex_matches,
    _convert_python_regex_to_javascript, _format_regex_converter_result,
    _format_regex_structure, _regex_zero_width_fragment,
    _regex_global_prefix, _regex_pattern_flag_state, _rewrite_regex_flags,
)


class RegexTesterTests(unittest.TestCase):
    def test_checkbox_flags_rewrite_only_global_prefix(self):
        self.assertEqual(_rewrite_regex_flags('.*U3.*', {'ignore_case': True}), '(?i).*U3.*')
        self.assertEqual(_rewrite_regex_flags('(?im)(?s)(?i:U3)', {'verbose': True}), '(?x)(?i:U3)')
        self.assertEqual(_rewrite_regex_flags('(?i)U3', {}), 'U3')
        self.assertEqual(_rewrite_regex_flags('(?u)U3', {'ascii_only': True}), '(?a)U3')
        self.assertEqual(_rewrite_regex_flags('(?u)U3', {'ignore_case': True}), '(?iu)U3')

    def test_typed_flags_ignore_scoped_and_incomplete_groups(self):
        state = _regex_pattern_flag_state('(?im)(?s)U3')
        self.assertTrue(state['ignore_case'] and state['multiline'] and state['dotall'])
        self.assertFalse(state['ascii_only'])
        for pattern in ('(?i:U3)', '(?im', r'\(\?i\)', 'U3(?i)'):
            self.assertFalse(any(_regex_pattern_flag_state(pattern).values()))
        self.assertEqual(_regex_global_prefix('(?i)(?m)U3')[0], 8)

    def test_session_restores_legacy_external_and_inline_flags_together(self):
        dialog = object.__new__(RegexTesterDialog)
        values = {}
        for name in ('pattern_edit', 'text_edit', 'summary', 'pattern_flags',
                     'ignore_case', 'multiline', 'dotall', 'verbose', 'ascii_only'):
            setattr(dialog, name, name)
        dialog.control_value = lambda control, default=None: values.get(control, default)
        dialog.set_control_value = lambda control, value: values.__setitem__(control, value)
        dialog._schedule_live_test = Mock()
        dialog._set_tool_mode = Mock()
        dialog._flag_sync_guard = True
        self.assertTrue(dialog._restore_regex_session({
            'pattern': '(?i)(?s:U3)', 'flags': {'multiline': True}}))
        self.assertEqual(values['pattern_edit'], '(?im)(?s:U3)')
        self.assertEqual(values['pattern_flags'], 'gim')
        self.assertFalse(values['dotall'])
        dialog._flag_sync_guard = False
        values['pattern_edit'] = '(?x)U3'
        dialog._sync_flags_from_pattern()
        self.assertTrue(values['verbose'])
        self.assertFalse(values['ignore_case'])
        self.assertFalse(values['multiline'])
        self.assertEqual(values['pattern_flags'], 'gx')

    def test_extracts_first_literal_pattern_from_formula(self):
        self.assertEqual(
            _first_regex_pattern(r'combine(regex(r"\\bU2_ANTIALIASING\\b"), -regex(".*RF2.*"))'),
            r'\\bU2_ANTIALIASING\\b')
        self.assertEqual(_first_regex_pattern('regex("A[0-9]+")'), 'A[0-9]+')
        self.assertEqual(_first_regex_pattern('combine(U3, RF3)'), '')
        self.assertEqual(_first_regex_pattern('regex("broken"'), '')

    def test_history_catalog_becomes_unique_test_lines(self):
        history = [
            {'displayName': 'U1'}, {'displayName': 'RF1'},
            {'displayName': 'U1'}, {'output': 'U2'}, 'RF2',
        ]
        self.assertEqual(_regex_test_text(history), 'U1\nRF1\nU2\nRF2')

    def test_evaluate_reports_matches_spans_groups_and_named_groups(self):
        result = RegexTesterDialog.evaluate(
            r'(?P<axis>U)([1-3])', 'U1 RF1 U2\nU3')
        self.assertFalse(result['error'])
        self.assertEqual([m['value'] for m in result['matches']], ['U1', 'U2', 'U3'])
        self.assertEqual(result['matches'][0]['span'], (0, 2))
        self.assertEqual(result['matches'][0]['groups'][0]['value'], 'U')
        self.assertEqual(result['matches'][0]['groups'][1]['value'], '1')
        self.assertEqual(result['matches'][0]['named']['axis'], 'U')
        self.assertEqual(result['group_count'], 2)
        self.assertEqual(result['named_groups'], {'axis': 1})

    def test_evaluate_supports_python_regex_flags(self):
        self.assertEqual(len(RegexTesterDialog.evaluate('^u1$', 'U1\nU2',
            ignore_case=True, multiline=True)['matches']), 1)
        self.assertEqual(len(RegexTesterDialog.evaluate('U1.*RF1', 'U1\nRF1',
            dotall=True)['matches']), 1)

    def test_invalid_regex_is_reported_without_raising(self):
        result = RegexTesterDialog.evaluate('([', 'U1')
        self.assertTrue(result['error'])
        self.assertEqual(result['matches'], [])


    def test_highlight_fragments_split_matches_across_lines(self):
        self.assertEqual(
            _regex_highlight_fragments('AA\nBB\nCC', [(1, 7)]),
            [(0, 'A', 'A'), (1, '', 'BB'), (2, '', 'C')],
        )
        self.assertEqual(
            _regex_highlight_fragments('U1 RF1 U2', [(0, 2), (7, 9)]),
            [(0, '', 'U1'), (0, 'U1 RF1 ', 'U2')],
        )

    def test_match_overlay_uses_front_viewport_layer_at_editor_screen_rect(self):
        import WinUx.dialogs.reference_chart_form as module
        fake = Mock()
        fake.does_item_exist.return_value = True
        fake.is_item_shown.return_value = True
        fake.get_text_size.side_effect = lambda text: [len(str(text)) * 7, 14]
        fake.get_x_scroll.return_value = 0
        fake.get_y_scroll.return_value = 0
        fake.add_viewport_drawlist.return_value = 'viewport-layer'
        original = module.dpg
        module.dpg = fake
        try:
            overlay = _RegexMatchOverlay('editor')
            with patch('DearUIQt.gui.placement.item_screen_rect',
                       return_value=(124, 282, 781, 432)):
                overlay.set_matches('U3_Anitialising', [(0, 15)])
        finally:
            module.dpg = original

        fake.add_viewport_drawlist.assert_called_once_with(front=True)
        self.assertFalse(fake.add_drawlist.called)
        fake.configure_item.assert_any_call('viewport-layer', show=True)
        self.assertGreaterEqual(fake.draw_rectangle.call_count, 1)
        call = fake.draw_rectangle.call_args_list[0]
        self.assertEqual(call.kwargs.get('fill'), _RegexMatchOverlay.SELECTED_FILL)
        self.assertEqual(call.kwargs.get('parent'), 'viewport-layer')
        # Rectangles are screen/viewport coordinates, not a second layout box.
        self.assertGreaterEqual(call.args[0][0], 124)
        self.assertGreaterEqual(call.args[0][1], 282)


    def test_live_refresh_updates_overlay_and_result_without_button(self):
        dialog = object.__new__(RegexTesterDialog)
        dialog._finished = False
        dialog._live_after = None
        dialog._overlay_after = None
        dialog.pattern_edit = 'pattern'
        dialog.text_edit = 'text'
        dialog.ignore_case = 'ignore'
        dialog.multiline = 'multi'
        dialog.dotall = 'dotall'
        dialog.verbose = 'verbose'
        dialog.ascii_only = 'ascii'
        dialog.explanation_edit = 'explanation'
        dialog.pattern_status = 'pattern_status'
        dialog.summary = 'summary'
        dialog.results_edit = 'results'
        dialog.match_position = 'match_position'
        dialog.match_prev_button = None
        dialog.match_next_button = None
        dialog._selected_match_index = 0
        dialog._last_live_result = {'matches': []}
        dialog._match_overlay = Mock()
        dialog._match_overlay.ranges = [(0, 2), (7, 9)]
        values = {
            'pattern': r'U[12]', 'text': 'U1 RF1 U2',
            'ignore': False, 'multi': False, 'dotall': False,
            'verbose': False, 'ascii': False,
        }
        dialog.control_value = lambda control, default=None: values.get(control, default)
        written = {}
        dialog.set_control_value = lambda control, value: written.__setitem__(control, value)
        dialog._schedule_overlay_sync = Mock()
        dialog._cancel_after = Mock()

        self.assertTrue(RegexTesterDialog._run_live_regex(dialog))
        dialog._match_overlay.set_matches.assert_called_once_with(
            'U1 RF1 U2', [(0, 2), (7, 9)], [], selected_index=0)
        dialog._schedule_overlay_sync.assert_called_once_with()
        self.assertIn('2 matches', written['summary'])
        self.assertIn('2 matches', written['pattern_status'])
        self.assertIn('Python re', written['summary'])
        self.assertIn('live', written['summary'])
        self.assertIn('MATCH 1 OF 2', written['results'])
        self.assertEqual(written['match_position'], '1 / 2')
        self.assertIn("Full match   0-2   'U1'", written['results'])
        self.assertIn('character set', written['explanation'])


    def test_regex101_explanation_covers_common_tokens(self):
        items = _regex_token_explanations(r'^(?P<axis>U\d+)(?:_RF)?$')
        descriptions = [item[3] for item in items]
        self.assertIn('start anchor', descriptions)
        self.assertIn('named capturing group', descriptions)
        self.assertIn('digit character', descriptions)
        self.assertIn('1 or more', descriptions)
        self.assertIn('non-capturing group', descriptions)
        self.assertIn('end anchor', descriptions)
        text = _format_regex_explanation(r'^(?P<axis>U[1-3]+)$')
        self.assertIn('1st named capturing group <axis>', text)
        self.assertIn('character set', text)
        self.assertIn('1 or more', text)
        self.assertIn('end group', text)

    def test_match_information_is_regex101_style(self):
        result = RegexTesterDialog.evaluate(r'(?P<axis>U)(\d)', 'U1 U2')
        info = _format_regex_match_information(result)
        self.assertIn('MATCH 1', info)
        self.assertIn('Full match', info)
        self.assertIn('Group 1', info)
        self.assertIn('Named <axis>', info)
        self.assertGreaterEqual(result['elapsed_ms'], 0.0)

    def test_quick_reference_contains_python_regex_basics(self):
        text = _format_regex_quick_reference()
        self.assertIn('COMMON TOKENS', text)
        self.assertIn(r'\d', text)
        self.assertIn('(?P<name>abc)', text)
        self.assertIn('Positive lookahead', text)

    def test_quick_reference_search_filters_entries(self):
        text = _format_regex_quick_reference('lookahead')
        self.assertIn('(?=abc)', text)
        self.assertIn('(?!abc)', text)
        self.assertNotIn('Digit character', text)
        self.assertIn('No quick-reference entries', _format_regex_quick_reference('zzzz-no-hit'))

    def test_evaluate_supports_verbose_and_ascii_flags(self):
        verbose = RegexTesterDialog.evaluate(r'U \d', 'U3', verbose=True)
        self.assertEqual([m['value'] for m in verbose['matches']], ['U3'])
        ascii_result = RegexTesterDialog.evaluate(r'\w+', 'café', ascii_only=True)
        self.assertEqual(ascii_result['matches'][0]['value'], 'caf')

    def test_live_match_count_is_bounded_for_responsive_inspector(self):
        old_limit = RegexTesterDialog.MAX_LIVE_MATCHES
        try:
            RegexTesterDialog.MAX_LIVE_MATCHES = 3
            result = RegexTesterDialog.evaluate('.', 'abcdef')
        finally:
            RegexTesterDialog.MAX_LIVE_MATCHES = old_limit
        self.assertEqual(len(result['matches']), 3)
        self.assertTrue(result['truncated'])

    def test_line_column_and_selected_match_information(self):
        result = RegexTesterDialog.evaluate(r'(U\d)', 'AA\nU1 BB\nU2')
        self.assertEqual(_regex_line_column('AA\nU1', 3), (2, 1))
        self.assertEqual(result['matches'][0]['line_column'], (2, 1))
        selected = _format_regex_selected_match(result, 1)
        self.assertIn('MATCH 2 OF 2', selected)
        self.assertIn('line 3, col 1', selected)
        self.assertIn('Group 1', selected)

    def test_match_navigation_wraps(self):
        dialog = object.__new__(RegexTesterDialog)
        dialog._last_live_result = RegexTesterDialog.evaluate(r'U\d', 'U1 U2')
        dialog._selected_match_index = 0
        dialog.results_edit = 'results'
        dialog.match_position = 'position'
        dialog.match_prev_button = None
        dialog.match_next_button = None
        written = {}
        dialog.set_control_value = lambda control, value: written.__setitem__(control, value)
        self.assertTrue(RegexTesterDialog._previous_match(dialog))
        self.assertEqual(dialog._selected_match_index, 1)
        self.assertEqual(written['position'], '2 / 2')
        self.assertTrue(RegexTesterDialog._next_match(dialog))
        self.assertEqual(dialog._selected_match_index, 0)
        dialog._match_information_view = 'Selected only'
        self.assertTrue(dialog._next_match())
        self.assertIn('MATCH 2 OF 2', written['results'])
        self.assertIn("'U2'", written['results'])
        self.assertNotIn("'U1'", written['results'])
        self.assertIn('Location', written['results'])

    def test_jump_to_match_validates_one_based_result_number(self):
        dialog = object.__new__(RegexTesterDialog)
        dialog._last_live_result = RegexTesterDialog.evaluate('U[12]', 'U1 U2')
        dialog._selected_match_index = 0
        dialog.match_jump_edit, dialog.summary = 'jump', 'summary'
        dialog._render_selected_match = Mock(return_value=True)
        dialog._reveal_selected_match = Mock()
        dialog.set_control_value = Mock()
        for value in ('', '0', '-1', '3', '1.5', 'abc', '١', '9' * 100):
            dialog.control_value = lambda *args: value
            self.assertFalse(dialog._jump_to_match())
            self.assertEqual(dialog._selected_match_index, 0)
        dialog._render_selected_match.assert_not_called()
        dialog._reveal_selected_match.assert_not_called()
        dialog.control_value = lambda *args: ' 2 '
        self.assertTrue(dialog._jump_to_match())
        self.assertEqual(dialog._selected_match_index, 1)
        dialog._render_selected_match.assert_called_once_with()
        dialog._reveal_selected_match.assert_called_once_with()
        dialog._last_live_result = {'matches': []}
        self.assertFalse(dialog._jump_to_match())

    def test_match_view_change_does_not_erase_regex_error(self):
        dialog = object.__new__(RegexTesterDialog)
        dialog._last_live_result = {'matches': [], 'error': 'unterminated group'}
        dialog._render_selected_match = Mock()
        dialog._reveal_selected_match = Mock()
        self.assertFalse(dialog._match_view_changed(value='Selected only'))
        self.assertEqual(dialog._match_information_view, 'Selected only')
        dialog._render_selected_match.assert_not_called()
        dialog._reveal_selected_match.assert_not_called()

    def test_input_change_debounces_live_matching(self):
        after = Mock(return_value=77)
        after_cancel = Mock(return_value=True)
        dialog = object.__new__(RegexTesterDialog)
        dialog._finished = False
        dialog._live_after = 12
        dialog._sync_flags_from_pattern = Mock()
        dialog.view = SimpleNamespace(after=after, after_cancel=after_cancel)
        RegexTesterDialog._input_changed(dialog)
        after_cancel.assert_called_once_with(12)
        after.assert_called_once_with(RegexTesterDialog.LIVE_DEBOUNCE_MS, dialog._run_live_regex)
        self.assertEqual(dialog._live_after, 77)

    def test_subject_metadata_counts_lines_and_unicode_characters(self):
        dialog = object.__new__(RegexTesterDialog)
        dialog.text_edit = 'text'
        for text, expected in (('', '1 line · 0 chars'), ('U1', '1 line · 2 chars'),
                               ('🙂\nU1', '2 lines · 4 chars'), ('U1\n', '2 lines · 3 chars')):
            dialog.control_value = lambda *args: text
            self.assertEqual(dialog._subject_metadata(), expected)

    def test_clear_subject_preserves_pattern_and_uses_undoable_native_edit(self):
        dialog = object.__new__(RegexTesterDialog)
        dialog.text_edit = 'subject'
        field = Mock()
        field.text.return_value = 'U1\nRF3'
        dialog.control_wrapper = Mock(return_value=field)
        dialog._input_changed = Mock()
        dialog.focus_control = Mock()
        dialog._clear_regex_subject()
        field.replace_prefix.assert_called_once_with(6, '')
        dialog.control_wrapper.assert_called_once_with('subject')
        dialog._input_changed.assert_called_once_with()
        dialog.focus_control.assert_called_once_with('subject')

    def test_explicit_navigation_reveals_subject_and_inspector_without_focus(self):
        dialog = object.__new__(RegexTesterDialog)
        dialog._native_regex_fields = [object()]
        dialog._tool_mode = 'match'
        dialog._last_live_result = RegexTesterDialog.evaluate('U1', '🙂\nU1')
        dialog._selected_match_index = 0
        dialog.text_edit, dialog.results_edit = 'subject', 'info'
        subject, info = Mock(), Mock()
        subject.text.return_value = '🙂\nU1'
        info.text.return_value = 'MATCH 1 OF 1 · selected\n\nMATCH 1\nFull match'
        dialog.control_wrapper = lambda control: subject if control == 'subject' else info
        dialog._sync_line_number_scroll = Mock()
        self.assertTrue(dialog._reveal_selected_match())
        subject.reveal_position.assert_called_once_with(2)
        info.reveal_position.assert_called_once_with(info.text.return_value.index('\nMATCH 1\n') + 1)
        subject.setFocus.assert_not_called()
        dialog._sync_line_number_scroll.assert_called_once_with()

        subject.reveal_position.reset_mock()
        info.reveal_position.reset_mock()
        for text, mode in (('changed', 'match'), ('🙂\nU1', 'substitution')):
            subject.text.return_value = text
            dialog._tool_mode = mode
            self.assertFalse(dialog._reveal_selected_match())
        subject.reveal_position.assert_not_called()
        info.reveal_position.assert_not_called()


    def test_live_header_summary_formats_match_counts(self):
        self.assertIn('1 match', _format_regex_live_header(1, 5, 0.123, group_count=0))
        self.assertIn('2 matches', _format_regex_live_header(2, 8, 0.456, group_count=1, named_count=1))
        self.assertIn('Regex error', _format_regex_live_header(0, 3, 0.789, error='bad regex'))

    def test_regex101_flag_bar_and_microsecond_timing(self):
        self.assertEqual(_regex_flag_letters(), 'g')
        self.assertEqual(
            _regex_flag_letters(ignore_case=True, multiline=True, dotall=True), 'gims')
        self.assertEqual(_format_regex_elapsed(0.017), '17 µs')
        self.assertIn('17 µs', _format_regex_live_header(1, 2, 0.017))
        flags = _format_regex_flag_explanation('gim')
        self.assertIn('GLOBAL PATTERN FLAGS', flags)
        self.assertIn('m modifier', flags)

    def test_test_string_line_number_gutter(self):
        self.assertEqual(_regex_line_numbers(''), '1')
        self.assertEqual(_regex_line_numbers('a\nb\nc'), '1\n2\n3')


    def test_substitution_accepts_regex101_replacement_tokens(self):
        self.assertEqual(_normalize_regex_replacement('$1-${name}-$&-$$'),
                         r'\g<1>-\g<name>-\g<0>-$')
        result = _evaluate_regex_substitution(
            r'(?P<name>U)(\d)', 'U1 U2', '${name}-$2')
        self.assertFalse(result['error'])
        self.assertEqual(result['output'], 'U-1 U-2')
        self.assertEqual(result['count'], 2)

    def test_substitution_reports_invalid_group_reference(self):
        result = _evaluate_regex_substitution(r'(U)', 'U1', '$9')
        self.assertTrue(result['error'])
        self.assertEqual(result['count'], 0)

    def test_unit_test_parser_and_live_evaluator(self):
        source = 'U1 => 1\nRF1 => no match\nU2 U3 => 2\n# ignored'
        parsed = _parse_regex_unit_tests(source)
        self.assertEqual(len(parsed), 3)
        result = _evaluate_regex_unit_tests(r'U\d', source)
        self.assertFalse(result['error'])
        self.assertEqual(result['passed'], 3)
        self.assertEqual(result['failed'], 0)
        formatted = _format_regex_unit_test_results(result)
        self.assertIn('PASS  Test 1', formatted)
        self.assertIn('PASS  Test 3', formatted)

    def test_unit_test_failures_are_reported_without_crashing(self):
        result = _evaluate_regex_unit_tests(r'U\d', 'U1 => 0\nbroken row')
        self.assertEqual(result['passed'], 0)
        self.assertEqual(result['failed'], 2)
        formatted = _format_regex_unit_test_results(result)
        self.assertIn('FAIL', formatted)
        self.assertIn('expected syntax', formatted)

    def test_python_code_generator_carries_flags_and_substitution(self):
        code = _python_regex_code(
            r'(?P<axis>U\d)', 'U1', '${axis}',
            ignore_case=True, multiline=True, substitution=True)
        self.assertIn('import re', code)
        self.assertIn('re.IGNORECASE | re.MULTILINE', code)
        self.assertIn("pattern.subn", code)
        self.assertIn(r'\\g<axis>', code)

    def test_unit_tests_can_compare_exact_full_match_values(self):
        source = 'U1 U2 => ["U1", "U2"]\nU3 => "U3"\nRF1 => []'
        result = _evaluate_regex_unit_tests(r'U\d', source)
        self.assertEqual(result['passed'], 3)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(result['tests'][0]['actual_values'], ['U1', 'U2'])
        formatted = _format_regex_unit_test_results(result)
        self.assertIn("['U1', 'U2']", formatted)

    def test_debug_trace_reports_prefix_match_and_incomplete_steps(self):
        result = _regex_debug_trace(r'(U\d+)', 'AA U12 BB')
        self.assertTrue(result['rows'])
        states = [row['state'] for row in result['rows']]
        self.assertIn('incomplete', states)
        self.assertIn('match', states)
        formatted = _format_regex_debug_trace(result)
        self.assertIn('MATCH', formatted)
        self.assertIn('capturing group', formatted)

    def test_benchmark_returns_timing_and_match_count(self):
        result = _benchmark_regex(r'U\d', 'U1 RF1 U2', iterations=5)
        self.assertFalse(result['error'])
        self.assertEqual(result['iterations'], 5)
        self.assertEqual(result['matches_per_run'], 2)
        self.assertGreaterEqual(result['average_ms'], 0.0)
        formatted = _format_regex_benchmark(result)
        self.assertIn('BENCHMARK RESULT', formatted)
        self.assertIn('Matches / run    2', formatted)

    def test_regex_session_json_roundtrip(self):
        encoded = _serialize_regex_session(
            r'U\d', 'U1\nU2', '$&', 'U1 => 1',
            extraction_template='$&\n', tool_mode='extraction',
            export_format='CSV', ignore_case=True, multiline=True)
        decoded = _deserialize_regex_session(encoded)
        self.assertFalse(decoded['error'])
        self.assertEqual(decoded['pattern'], r'U\d')
        self.assertEqual(decoded['text'], 'U1\nU2')
        self.assertEqual(decoded['replacement'], '$&')
        self.assertEqual(decoded['extraction_template'], '$&\n')
        self.assertEqual(decoded['tool_mode'], 'extraction')
        self.assertEqual(decoded['export_format'], 'CSV')
        self.assertTrue(decoded['flags']['ignore_case'])
        self.assertTrue(decoded['flags']['multiline'])
        self.assertFalse(_deserialize_regex_session('{}').get('error') == '')


    def test_extraction_discards_unmatched_text_and_expands_groups(self):
        result = _evaluate_regex_extraction(
            r'ORD-(?P<id>\d{4})',
            'ORD-0042 pending\nnoise\nORD-0187 sent',
            '${id}\n')
        self.assertFalse(result['error'])
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['output'], '0042\n0187\n')

    def test_export_matches_supports_json_jsonl_csv_and_plain_text(self):
        result = RegexTesterDialog.evaluate(r'(?P<axis>U)(\d)', 'U1 U2')
        json_text = _export_regex_matches(result, 'JSON')
        self.assertIn('"value": "U1"', json_text)
        jsonl = _export_regex_matches(result, 'JSON Lines')
        self.assertEqual(len(jsonl.splitlines()), 2)
        csv_text = _export_regex_matches(result, 'CSV')
        self.assertIn('named_axis', csv_text.splitlines()[0])
        self.assertIn('U1', csv_text)
        self.assertEqual(_export_regex_matches(result, 'Plain Text'), 'U1\nU2')

    def test_python_to_javascript_converter_handles_named_groups_and_findings(self):
        converted = _convert_python_regex_to_javascript(
            r'^(?P<id>\d+)-(?P=id)$', ignore_case=True, verbose=True)
        self.assertIn('(?<id>', converted['pattern'])
        self.assertIn(r'\k<id>', converted['pattern'])
        self.assertEqual(converted['flags'], 'gi')
        self.assertEqual(converted['status'], 'Approximate')
        self.assertTrue(converted['warnings'])
        formatted = _format_regex_converter_result(converted)
        self.assertIn('TARGET  JavaScript RegExp', formatted)
        self.assertIn('WARNINGS', formatted)

    def test_regex_compile_error_exposes_position_line_and_column(self):
        result = RegexTesterDialog.evaluate('abc\n([', 'anything')
        self.assertTrue(result['error'])
        self.assertIsNotNone(result.get('error_position'))
        self.assertIsNotNone(result.get('error_line'))
        self.assertIsNotNone(result.get('error_column'))

    def test_zero_width_location_and_overlay_marker(self):
        self.assertEqual(_regex_zero_width_fragment('AA\nBB', 3), (1, ''))
        import WinUx.dialogs.reference_chart_form as module
        fake = Mock()
        fake.does_item_exist.return_value = True
        fake.is_item_shown.return_value = True
        fake.get_text_size.side_effect = lambda text: [len(str(text)) * 7, 14]
        fake.get_x_scroll.return_value = 0
        fake.get_y_scroll.return_value = 0
        fake.add_viewport_drawlist.return_value = 'viewport-layer'
        original = module.dpg
        module.dpg = fake
        try:
            overlay = _RegexMatchOverlay('editor')
            with patch('DearUIQt.gui.placement.item_screen_rect',
                       return_value=(100, 200, 500, 400)):
                overlay.set_matches('AA\nBB', [(3, 3)])
        finally:
            module.dpg = original
        self.assertEqual(overlay.ranges, [(3, 3)])
        self.assertGreaterEqual(fake.draw_line.call_count, 1)

    def test_structural_formatter_preserves_pattern_tokens(self):
        formatted = _format_regex_structure(r'^(U\d+)(?:_RF)?$')
        self.assertIn('^', formatted)
        self.assertIn('(', formatted)
        self.assertIn(r'\d', formatted)
        self.assertIn('$', formatted)


    def test_function_selector_routes_to_compact_modes(self):
        dialog = object.__new__(RegexTesterDialog)
        dialog._mode_selector_guard = False
        dialog._finished = False
        dialog.function_selector = 'function'
        dialog.control_value = lambda control, default=None: 'Extraction' if control == 'function' else default
        dialog._set_tool_mode = Mock(return_value=True)
        self.assertTrue(RegexTesterDialog._function_mode_changed(dialog))
        dialog._set_tool_mode.assert_called_once_with('extraction')

    def test_tools_selector_routes_to_tool_mode(self):
        dialog = object.__new__(RegexTesterDialog)
        dialog._mode_selector_guard = False
        dialog._finished = False
        dialog.tools_selector = 'tools'
        dialog.control_value = lambda control, default=None: 'Regex Debugger' if control == 'tools' else default
        dialog._set_tool_mode = Mock(return_value=True)
        self.assertTrue(RegexTesterDialog._tools_mode_changed(dialog))
        dialog._set_tool_mode.assert_called_once_with('debug')

    def test_inspector_toggle_uses_ascii_labels(self):
        import WinUx.dialogs.reference_chart_form as module
        fake = Mock()
        original = module.dpg
        module.dpg = fake
        try:
            dialog = object.__new__(RegexTesterDialog)
            self.assertTrue(RegexTesterDialog._set_inspector_visible(dialog, ['body'], 'toggle', True))
            fake.configure_item.assert_any_call('toggle', label='-')
            fake.reset_mock()
            self.assertFalse(RegexTesterDialog._set_inspector_visible(dialog, ['body'], 'toggle', False))
            fake.configure_item.assert_any_call('toggle', label='+')
        finally:
            module.dpg = original

    @patch('WinUx.dialogs.reference_chart_form.RegexTesterDialog')
    def test_check_regex_opens_owned_dialog_seeded_from_formula_and_history(self, dialog_cls):
        child = SimpleNamespace()
        dialog_cls.return_value = child
        controls = {'formula': 'combine(regex(".*U2.*"), regex(".*RF2.*"))'}
        parent = SimpleNamespace(
            _finished=False, formula_edit='formula',
            _history_outputs=[{'displayName': 'U2'}, {'displayName': 'RF2'}],
            _regex_tester_dialog=None, view='view',
            control_value=lambda control, default=None: controls.get(control, default),
            own_dialog=Mock(return_value=child),
        )
        self.assertTrue(ReferenceChartDialog._open_regex_tester(parent))
        dialog_cls.assert_called_once_with(
            'view', pattern='.*U2.*', text='U2\nRF2', parent=parent)
        parent.own_dialog.assert_called_once_with(child)
        self.assertIs(parent._regex_tester_dialog, child)


if __name__ == '__main__':
    unittest.main(verbosity=2)
