"""Pure lexer/color contracts for Check Regex; no GUI or physical input."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from WinUx.ui.components.regex_syntax import (
    regex_syntax_tokens, REGEX_GROUP_COLORS, REGEX_SYNTAX_COLORS,
    REGEX_GROUP_BACKGROUNDS, regex_pattern_spans, regex_subject_spans,
    regex_inspector_spans, regex_explanation_spans,
)


class RegexSyntaxTests(unittest.TestCase):
    def test_python_offsets_map_to_native_utf16_without_changing_newlines(self):
        import run_winux
        run_winux._configure_bundled_dependencies(str(Path(__file__).resolve().parents[1]))
        from WinUx.ui.components.regex_rich_edit import utf16_offsets
        self.assertEqual(utf16_offsets('A🙂\nBé'), [0, 1, 3, 4, 5, 6])

    def test_inline_nested_capture_backgrounds_are_consistent(self):
        pattern = r'((U)\d)'
        spans = regex_pattern_spans(pattern)
        by_start = {start: background for start, end, fg, background in spans}
        self.assertEqual(by_start[0], REGEX_GROUP_BACKGROUNDS[0])
        self.assertEqual(by_start[1], REGEX_GROUP_BACKGROUNDS[1])
        self.assertEqual(by_start[2], REGEX_GROUP_BACKGROUNDS[1])
        self.assertEqual(by_start[4], REGEX_GROUP_BACKGROUNDS[0])

    def test_inline_match_colors_cover_each_match_not_only_selected(self):
        result = {'matches': [
            {'span': (0, 2), 'groups': [{'span': (0, 1), 'index': 1}]},
            {'span': (3, 5), 'groups': [{'span': (3, 4), 'index': 1}]},
        ]}
        spans = regex_subject_spans(result, 1)
        captures = [span for span in spans if span[3] == REGEX_GROUP_BACKGROUNDS[0]]
        self.assertEqual([(span[0], span[1]) for span in captures], [(0, 1), (3, 4)])
        self.assertNotEqual(spans[0][3], spans[2][3])  # Selected full match is stronger.

    def test_unmatched_and_zero_width_captures_do_not_rewrite_subject(self):
        result = {'matches': [{'span': (2, 2), 'groups': [
            {'span': (-1, -1), 'index': 1}, {'span': (2, 2), 'index': 2}]}]}
        self.assertEqual(regex_subject_spans(result), [])
        self.assertEqual(result['matches'][0]['span'], (2, 2))

    def test_inline_formatting_budget_is_bounded(self):
        self.assertLessEqual(len(regex_pattern_spans('(a)' * 20, limit=4)), 4)
        result = {'matches': [{'span': (i, i + 1), 'groups': []} for i in range(30)]}
        self.assertEqual(len(regex_subject_spans(result, limit=4)), 4)

    def test_inspector_uses_same_capture_color_for_names_and_numbers(self):
        text = "MATCH 1\nFull match 0-2 'U1'\nGroup 1 0-1 'U'\nNamed <kind> 'U'"
        spans = regex_inspector_spans(text, {'kind': 1})
        self.assertEqual(len(spans), 3)
        self.assertEqual(spans[1][3], REGEX_GROUP_BACKGROUNDS[0])
        self.assertEqual(spans[2][3], REGEX_GROUP_BACKGROUNDS[0])

    def test_explanation_colors_both_header_pattern_and_token_labels(self):
        pattern = '(U)'
        explanation = pattern + "\n\n[0:1] '(' capturing group\n[1:2] 'U' literal text"
        spans = regex_explanation_spans(pattern, explanation)
        self.assertTrue(any(start > len(pattern) and explanation[start:end] == "'('"
                            for start, end, fg, bg in spans))
        self.assertEqual(spans[0][3], REGEX_GROUP_BACKGROUNDS[0])

    def tokens(self, pattern, **kwargs):
        tokens = regex_syntax_tokens(pattern, **kwargs)
        self.assertEqual(''.join(token['text'] for token in tokens), pattern)
        offset = 0
        for token in tokens:
            self.assertEqual(token['start'], offset)
            self.assertGreater(token['end'], offset)
            self.assertEqual(token['text'], pattern[offset:token['end']])
            offset = token['end']
        self.assertEqual(offset, len(pattern))
        return tokens

    def test_basic_token_colors(self):
        tokens = self.tokens(r'^U[1-3]+|RF\d{2,4}?$')
        self.assertEqual([token['kind'] for token in tokens], [
            'anchor', 'literal', 'class', 'quantifier', 'alternation',
            'literal', 'class', 'quantifier', 'anchor'])
        self.assertGreaterEqual(len({token['color'] for token in tokens}), 5)

    def test_capture_delimiters_and_named_reference_share_palette(self):
        tokens = self.tokens(r'(?P<axis>U\d+)([1-3])(?P=axis)')
        group1 = [token for token in tokens if token['group'] == 1]
        group2 = [token for token in tokens if token['group'] == 2]
        self.assertEqual(len(group1), 3)
        self.assertEqual(len(group2), 2)
        self.assertTrue(all(t['color'] == REGEX_GROUP_COLORS[0] for t in group1))
        self.assertTrue(all(t['color'] == REGEX_GROUP_COLORS[1] for t in group2))

    def test_non_capturing_groups_and_lookarounds_do_not_consume_numbers(self):
        tokens = self.tokens(r'(?<=A)(?:B)(?=C)(D)')
        self.assertEqual([t['group'] for t in tokens if t['text'] == '('], [1])

    def test_class_literal_closing_bracket_and_escaped_brackets(self):
        for pattern in (r'[]a]+', r'[^]a]+', r'[a\]b]+', r'[()#]+'):
            with self.subTest(pattern=pattern):
                tokens = self.tokens(pattern, verbose=True)
                self.assertEqual(tokens[0]['kind'], 'class')
                self.assertEqual(tokens[0]['text'], pattern[:-1])
                self.assertTrue(all(t['group'] is None for t in tokens))

    def test_verbose_comments_do_not_create_fake_groups(self):
        tokens = self.tokens('(?x) U # (fake)\n(V)(?# (ignored)', verbose=False)
        captures = [t for t in tokens if t['group'] is not None]
        self.assertEqual({t['group'] for t in captures}, {1})
        self.assertTrue(any(t['kind'] == 'comment' and '# (fake)' in t['text'] for t in tokens))

    def test_scoped_verbose_flag_is_restored_after_group(self):
        tokens = self.tokens('(?x:A # comment\n)(?-x:B#literal)C#literal')
        comments = [t['text'] for t in tokens if t['kind'] == 'comment']
        self.assertEqual(comments, [' ', '# comment', '\n'])

    def test_escaped_hash_is_not_verbose_comment(self):
        tokens = self.tokens(r'\#([#])', verbose=True)
        self.assertFalse(any(t['kind'] == 'comment' for t in tokens))

    def test_unicode_hex_named_escapes_and_incomplete_input(self):
        for pattern in (r'\x41\u0042\U00000043\N{LATIN CAPITAL LETTER D}',
                        'é🙂(U[', '\\', '(?P<', '', '{not a quantifier}'):
            with self.subTest(pattern=pattern):
                self.tokens(pattern)

    def test_error_position_marks_exact_unicode_character(self):
        tokens = self.tokens('é🙂hello', error_position=3)
        errors = [t for t in tokens if t['kind'] == 'error']
        self.assertEqual([(t['start'], t['end'], t['text']) for t in errors], [(3, 4, 'e')])
        self.assertEqual(errors[0]['color'], REGEX_SYNTAX_COLORS['error'])

    def test_lazy_and_possessive_suffixes_stay_with_quantifiers(self):
        tokens = self.tokens('a*?b++c{,3}?')
        self.assertEqual([t['text'] for t in tokens if t['kind'] == 'quantifier'], ['*?', '++', '{,3}?'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
