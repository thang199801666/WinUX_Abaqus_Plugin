"""Regex101-style tester used by the Reference Chart formula editor.

This module owns regex parsing/evaluation helpers, live-match rendering, and the
standalone :class:`RegexTesterDialog`.  It intentionally has no dependency on
``ReferenceChartDialog`` so the workbench can evolve and be tested in isolation.
"""
from __future__ import annotations

import ast
import csv
import io
import json
import os
import re
import time
import sys

from DearUIQt.backends import dpg as _native_dpg
from DearUIQt.dialogs.qt_dialog import QtDialog
from DearUIQt.gui import QClipboard
from DearUIQt.layouts import QGridLayout
from DearUIQt.widgets import QFrame, QLabel

from ...ui.components.regex_syntax import (
    REGEX_GROUP_COLORS, regex_pattern_spans,
    regex_subject_spans, regex_inspector_spans, regex_explanation_spans)


class _LegacyDPGProxy:
    """Honor the historical ``reference_chart_form.dpg`` patch point.

    Older plugins/tests replace that module global while exercising native overlay
    behavior.  Keep that hook working even though the implementation now lives
    in this module.
    """

    def _target(self):
        module = sys.modules.get("WinUx.dialogs.reference.reference_chart_form")
        candidate = getattr(module, "dpg", None) if module is not None else None
        if candidate is not None and candidate is not self:
            return candidate
        return _native_dpg

    def __getattr__(self, name):
        return getattr(self._target(), name)


dpg = _LegacyDPGProxy()

REGEX_QUICK_REFERENCE = (
    ('.', 'Any character except newline (unless DOTALL is enabled).'),
    (r'\d', 'Digit character.'),
    (r'\D', 'Non-digit character.'),
    (r'\w', 'Word character.'),
    (r'\W', 'Non-word character.'),
    (r'\s', 'Whitespace character.'),
    (r'\S', 'Non-whitespace character.'),
    (r'\b', 'Word boundary.'),
    ('^', 'Start of string, or line with MULTILINE.'),
    ('$', 'End of string, or line with MULTILINE.'),
    ('[abc]', 'Character set.'),
    ('[^abc]', 'Negated character set.'),
    ('*', '0 or more of the previous token.'),
    ('+', '1 or more of the previous token.'),
    ('?', '0 or 1 of the previous token.'),
    ('{m,n}', 'Between m and n repetitions.'),
    ('(abc)', 'Capturing group.'),
    ('(?:abc)', 'Non-capturing group.'),
    ('(?P<name>abc)', 'Named capturing group.'),
    ('(?=abc)', 'Positive lookahead.'),
    ('(?!abc)', 'Negative lookahead.'),
    ('(?<=abc)', 'Positive lookbehind.'),
    ('(?<!abc)', 'Negative lookbehind.'),
    ('A|B', 'Alternation: A or B.'),
)

REGEX_QUICK_REFERENCE_GROUPS = (
    ('Common tokens', (
        ('.', 'Any character except newline (unless DOTALL is enabled).'),
        (r'\d', 'Digit character.'),
        (r'\D', 'Non-digit character.'),
        (r'\w', 'Word character.'),
        (r'\W', 'Non-word character.'),
        (r'\s', 'Whitespace character.'),
        (r'\S', 'Non-whitespace character.'),
        ('[abc]', 'Character set.'),
        ('[^abc]', 'Negated character set.'),
        ('[a-z]', 'Character in the range a-z.'),
        ('[^a-z]', 'Character not in the range a-z.'),
        ('[a-zA-Z]', 'ASCII alphabetic character.'),
    )),
    ('Anchors and boundaries', (
        (r'\b', 'Word boundary.'),
        (r'\B', 'Non-word boundary.'),
        ('^', 'Start of string, or line with MULTILINE.'),
        ('$', 'End of string, or line with MULTILINE.'),
        ('A|B', 'Alternation: A or B.'),
    )),
    ('Quantifiers', (
        ('*', '0 or more of the previous token.'),
        ('+', '1 or more of the previous token.'),
        ('?', '0 or 1 of the previous token.'),
        ('{m,n}', 'Between m and n repetitions.'),
        ('a{3}', 'Exactly 3 repetitions.'),
        ('a{3,}', '3 or more repetitions.'),
        ('a{3,6}', 'Between 3 and 6 repetitions.'),
    )),
    ('Groups and lookarounds', (
        ('(abc)', 'Capturing group.'),
        ('(?:abc)', 'Non-capturing group.'),
        ('(?P<name>abc)', 'Named capturing group.'),
        ('(?=abc)', 'Positive lookahead.'),
        ('(?!abc)', 'Negative lookahead.'),
        ('(?<=abc)', 'Positive lookbehind.'),
        ('(?<!abc)', 'Negative lookbehind.'),
    )),
)

_REGEX_ESCAPE_HELP = {
    'd': 'digit character', 'D': 'non-digit character',
    'w': 'word character', 'W': 'non-word character',
    's': 'whitespace character', 'S': 'non-whitespace character',
    'b': 'word boundary', 'B': 'non-word boundary',
    'A': 'start of string', 'Z': 'end of string', 'z': 'end of string',
    'n': 'newline', 'r': 'carriage return', 't': 'tab', 'f': 'form feed',
    'v': 'vertical tab',
}


def _ordinal(value):
    value = int(value or 0)
    if 10 <= (value % 100) <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(value % 10, 'th')
    return '{}{}'.format(value, suffix)


def _format_regex_elapsed(elapsed_ms):
    value = max(0.0, float(elapsed_ms or 0.0))
    if value < 1.0:
        return '{:.0f} µs'.format(value * 1000.0)
    if value < 1000.0:
        return '{:.3f} ms'.format(value)
    return '{:.3f} s'.format(value / 1000.0)


def _format_regex_live_header(match_count, token_count, elapsed_ms, *,
                              group_count=0, named_count=0, truncated=False, error=''):
    elapsed = _format_regex_elapsed(elapsed_ms)
    if error:
        return 'Regex error · {}'.format(elapsed)
    if truncated:
        match_text = '{}+ matches'.format(match_count)
    elif match_count == 1:
        match_text = '1 match'
    else:
        match_text = '{} matches'.format(match_count)
    return '{} · {} token{} · {} group{}{} · {}'.format(
        match_text,
        token_count, '' if token_count == 1 else 's',
        group_count, '' if group_count == 1 else 's',
        '' if not named_count else ' · {} named'.format(named_count),
        elapsed,
    )


def _regex_flag_letters(*, ignore_case=False, multiline=False, dotall=False,
                        verbose=False, ascii_only=False):
    letters = ['g']
    if ignore_case:
        letters.append('i')
    if multiline:
        letters.append('m')
    if dotall:
        letters.append('s')
    if verbose:
        letters.append('x')
    if ascii_only:
        letters.append('a')
    return ''.join(letters)


_REGEX_FLAG_KEYS = dict(zip('imsxa',
    ('ignore_case', 'multiline', 'dotall', 'verbose', 'ascii_only')))


def _regex_global_prefix(pattern):
    """Read complete leading global groups, never scoped/incomplete groups."""
    pattern = str(pattern or '')
    end, letters = 0, set()
    while True:
        match = re.match(r'\(\?([aiLmsux]+)\)', pattern[end:])
        if not match:
            return end, letters
        letters.update(match.group(1))
        end += match.end()


def _regex_pattern_flag_state(pattern):
    _, letters = _regex_global_prefix(pattern)
    return {key: letter in letters for letter, key in _REGEX_FLAG_KEYS.items()}


def _rewrite_regex_flags(pattern, state):
    end, letters = _regex_global_prefix(pattern)
    letters.difference_update(_REGEX_FLAG_KEYS)
    letters.update(letter for letter, key in _REGEX_FLAG_KEYS.items() if state.get(key))
    if 'a' in letters:
        letters.discard('u')  # Python forbids combining ASCII and Unicode modes.
    prefix = ''.join(letter for letter in 'aiLmsux' if letter in letters)
    return ('(?{})'.format(prefix) if prefix else '') + pattern[end:]


def _regex_line_numbers(text):
    count = max(1, str(text or '').count('\n') + 1)
    return '\n'.join(str(index) for index in range(1, count + 1))


def _regex_zero_width_fragment(text, position):
    source = str(text or '')
    try:
        position = max(0, min(len(source), int(position)))
    except (TypeError, ValueError):
        position = 0
    line_index = source.count('\n', 0, position)
    line_start = source.rfind('\n', 0, position) + 1
    return line_index, source[line_start:position]


def _normalize_regex_replacement(replacement):
    """Translate common regex101 replacement tokens to Python ``re`` syntax.

    Python's replacement grammar uses ``\\g<1>``/``\\g<name>`` while regex101
    commonly presents ``$1``/``${name}``.  Accept both so Formula authors can
    move between the workbench and regex101 without mentally translating them.
    """
    source = str(replacement or '')
    sentinel = '\x00REGEX_DOLLAR\x00'
    source = source.replace('$$', sentinel)
    source = source.replace('$&', r'\g<0>')
    source = re.sub(r'\$\{([A-Za-z_]\w*|\d+)\}', r'\\g<\1>', source)
    source = re.sub(r'\$(\d+)', r'\\g<\1>', source)
    return source.replace(sentinel, '$')


def _regex_flags_value(*, ignore_case=False, multiline=False, dotall=False,
                       verbose=False, ascii_only=False):
    flags = 0
    if ignore_case:
        flags |= re.IGNORECASE
    if multiline:
        flags |= re.MULTILINE
    if dotall:
        flags |= re.DOTALL
    if verbose:
        flags |= re.VERBOSE
    if ascii_only:
        flags |= re.ASCII
    return flags


def _evaluate_regex_substitution(pattern, text, replacement, *, ignore_case=False,
                                 multiline=False, dotall=False, verbose=False,
                                 ascii_only=False):
    flags = _regex_flags_value(
        ignore_case=ignore_case, multiline=multiline, dotall=dotall,
        verbose=verbose, ascii_only=ascii_only)
    started = time.perf_counter()
    try:
        compiled = re.compile(str(pattern or ''), flags)
        normalized = _normalize_regex_replacement(replacement)
        output, count = compiled.subn(normalized, str(text or ''))
        return {
            'error': '', 'output': output, 'count': int(count),
            'normalized_replacement': normalized,
            'elapsed_ms': (time.perf_counter() - started) * 1000.0,
        }
    except (re.error, TypeError, ValueError, IndexError) as exc:
        return {
            'error': str(exc), 'output': '', 'count': 0,
            'normalized_replacement': _normalize_regex_replacement(replacement),
            'elapsed_ms': (time.perf_counter() - started) * 1000.0,
        }



def _evaluate_regex_extraction(pattern, text, template='$&\n', *, ignore_case=False,
                               multiline=False, dotall=False, verbose=False,
                               ascii_only=False):
    """Return regex101-style extraction output for every match.

    Extraction differs from substitution: unmatched text is discarded and only
    the expanded extraction template for each match is concatenated.
    """
    flags = _regex_flags_value(
        ignore_case=ignore_case, multiline=multiline, dotall=dotall,
        verbose=verbose, ascii_only=ascii_only)
    started = time.perf_counter()
    normalized = _normalize_regex_replacement(template)
    try:
        compiled = re.compile(str(pattern or ''), flags)
        pieces = []
        count = 0
        for match in compiled.finditer(str(text or '')):
            pieces.append(match.expand(normalized))
            count += 1
        return {
            'error': '', 'output': ''.join(pieces), 'count': count,
            'normalized_template': normalized,
            'elapsed_ms': (time.perf_counter() - started) * 1000.0,
        }
    except (re.error, TypeError, ValueError, IndexError) as exc:
        return {
            'error': str(exc), 'output': '', 'count': 0,
            'normalized_template': normalized,
            'elapsed_ms': (time.perf_counter() - started) * 1000.0,
        }


def _regex_match_export_rows(result):
    rows = []
    for number, match in enumerate(list((result or {}).get('matches') or []), 1):
        start, end = match.get('span', (0, 0))
        row = {
            'match': number, 'value': match.get('value'),
            'start': start, 'end': end,
            'groups': [group.get('value') for group in (match.get('groups') or [])],
            'named': dict(match.get('named') or {}),
        }
        rows.append(row)
    return rows


def _export_regex_matches(result, format_name='JSON'):
    """Export live matches in regex101-style machine-readable formats."""
    rows = _regex_match_export_rows(result)
    fmt = str(format_name or 'JSON').strip().lower()
    if fmt in ('json',):
        return json.dumps(rows, indent=2, ensure_ascii=False)
    if fmt in ('json lines', 'jsonl', 'ndjson'):
        return '\n'.join(json.dumps(row, ensure_ascii=False) for row in rows)
    if fmt in ('plain text', 'text', 'txt'):
        return '\n'.join(str(row.get('value') or '') for row in rows)
    if fmt == 'csv':
        buffer = io.StringIO()
        group_count = max([len(row.get('groups') or []) for row in rows] or [0])
        named_keys = sorted({key for row in rows for key in (row.get('named') or {})})
        fieldnames = ['match', 'value', 'start', 'end']
        fieldnames += ['group_{}'.format(index) for index in range(1, group_count + 1)]
        fieldnames += ['named_{}'.format(name) for name in named_keys]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator='\n')
        writer.writeheader()
        for row in rows:
            flat = {key: row.get(key) for key in ('match', 'value', 'start', 'end')}
            for index, value in enumerate(row.get('groups') or [], 1):
                flat['group_{}'.format(index)] = value
            for name, value in (row.get('named') or {}).items():
                flat['named_{}'.format(name)] = value
            writer.writerow(flat)
        return buffer.getvalue().rstrip('\n')
    raise ValueError('Unsupported export format: {}'.format(format_name))


def _convert_python_regex_to_javascript(pattern, *, ignore_case=False, multiline=False,
                                         dotall=False, verbose=False, ascii_only=False):
    """Best-effort Python ``re`` -> JavaScript conversion with findings.

    This deliberately handles only transformations we can state confidently.
    Unsupported Python-only constructs are reported instead of silently changed.
    """
    source = str(pattern or '')
    converted = source
    changes = []
    warnings = []

    def replace_named_group(match):
        name = match.group(1)
        changes.append('Named group (?P<{}>...) -> (?<{}>...)'.format(name, name))
        return '(?<{}>'.format(name)

    converted = re.sub(r'\(\?P<([A-Za-z_]\w*)>', replace_named_group, converted)

    def replace_named_backref(match):
        name = match.group(1)
        changes.append(r'Named backreference (?P={}) -> \k<{}>'.format(name, name))
        return r'\k<{}>'.format(name)

    converted = re.sub(r'\(\?P=([A-Za-z_]\w*)\)', replace_named_backref, converted)
    if r'\A' in converted:
        converted = converted.replace(r'\A', '^')
        changes.append(r'\A -> ^ (approximate start-of-input conversion)')
    if r'\Z' in converted:
        converted = converted.replace(r'\Z', '$')
        changes.append(r'\Z -> $ (approximate end-of-input conversion)')
    if '(?(' in converted:
        warnings.append('Conditional groups are not supported by JavaScript RegExp.')
    if '(?#' in converted:
        warnings.append('Python comment groups are not supported by JavaScript RegExp.')
    if verbose:
        warnings.append('Python VERBOSE/x mode has no direct JavaScript RegExp flag equivalent.')
    if ascii_only:
        warnings.append('Python ASCII/a mode has no direct JavaScript RegExp flag equivalent.')
    flags = 'g'
    if ignore_case:
        flags += 'i'
    if multiline:
        flags += 'm'
    if dotall:
        flags += 's'
    status = 'Compatible' if not changes and not warnings else ('Converted' if not warnings else 'Approximate')
    return {
        'pattern': converted, 'flags': flags, 'changes': changes,
        'warnings': warnings, 'status': status,
    }


def _format_regex_converter_result(result):
    lines = [
        'TARGET  JavaScript RegExp',
        'STATUS  {}'.format((result or {}).get('status', 'Unknown')),
        '',
        '/{}/{}'.format((result or {}).get('pattern', ''), (result or {}).get('flags', 'g')),
    ]
    changes = list((result or {}).get('changes') or [])
    warnings = list((result or {}).get('warnings') or [])
    if changes:
        lines.extend(['', 'CHANGES'])
        lines.extend('• {}'.format(change) for change in changes)
    if warnings:
        lines.extend(['', 'WARNINGS'])
        lines.extend('• {}'.format(warning) for warning in warnings)
    if not changes and not warnings:
        lines.extend(['', 'No conversion changes are required for the supported syntax.'])
    return '\n'.join(lines)


def _format_regex_structure(pattern):
    """Return a non-destructive structural formatter for inspection/copying."""
    source = str(pattern or '')
    if not source:
        return 'Enter a regular expression to format it.'
    tokens = _regex_token_explanations(source)
    lines = []
    indent = 0
    for _start, _end, token, description in tokens:
        desc = str(description).lower()
        if desc == 'close group':
            indent = max(0, indent - 1)
        lines.append('{}{}'.format('    ' * indent, token))
        if ('group' in desc and desc != 'close group' and
                ('capturing group' in desc or 'lookahead' in desc or 'lookbehind' in desc or
                 'special/inline-flag group' in desc or 'comment group' in desc)):
            indent += 1
    return '\n'.join(lines)


def _regex_error_location(exc, pattern=''):
    pos = getattr(exc, 'pos', None)
    line = getattr(exc, 'lineno', None)
    col = getattr(exc, 'colno', None)
    if pos is not None and (line is None or col is None):
        line, col = _regex_line_column(str(pattern or ''), int(pos))
    return {
        'position': pos, 'line': line, 'column': col,
    }

def _parse_regex_unit_tests(source):
    """Parse compact ``text => expected`` regex unit-test rows.

    Supported expected values:
    - integer count, e.g. ``U1 U2 => 2``
    - ``match`` / ``no match``
    - quoted full-match text, e.g. ``U1 RF1 => "U1"``
    - a Python/JSON-like list of full matches, e.g. ``U1 U2 => ["U1", "U2"]``

    Blank lines and ``#`` comments are ignored.  ``rsplit`` deliberately lets
    the sample text itself contain ``=>``.
    """
    tests = []
    for line_number, raw in enumerate(str(source or '').splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if '=>' not in raw:
            tests.append({
                'line': line_number, 'text': raw, 'expected': None,
                'error': 'expected syntax: text => count|match|no match|"value"|["a", "b"]',
            })
            continue
        sample, expected_raw = raw.rsplit('=>', 1)
        sample = sample.rstrip()
        raw_token = expected_raw.strip()
        token = raw_token.lower()
        expected = None
        error = ''
        if token in ('match', 'true', 'yes', 'y'):
            expected = ('minimum', 1)
        elif token in ('no match', 'nomatch', 'false', 'no', 'n'):
            expected = ('exact', 0)
        else:
            try:
                expected = ('exact', max(0, int(token)))
            except (TypeError, ValueError):
                try:
                    literal = ast.literal_eval(raw_token)
                except (SyntaxError, ValueError, TypeError):
                    literal = None
                if isinstance(literal, str):
                    expected = ('values', [literal])
                elif isinstance(literal, (list, tuple)) and all(
                        isinstance(value, str) for value in literal):
                    expected = ('values', list(literal))
                else:
                    error = 'invalid expected value {}'.format(repr(raw_token))
        tests.append({
            'line': line_number, 'text': sample, 'expected': expected,
            'error': error,
        })
    return tests


def _evaluate_regex_unit_tests(pattern, source, *, ignore_case=False, multiline=False,
                               dotall=False, verbose=False, ascii_only=False):
    flags = _regex_flags_value(
        ignore_case=ignore_case, multiline=multiline, dotall=dotall,
        verbose=verbose, ascii_only=ascii_only)
    started = time.perf_counter()
    try:
        compiled = re.compile(str(pattern or ''), flags)
    except (re.error, TypeError) as exc:
        return {
            'error': str(exc), 'passed': 0, 'failed': 0, 'tests': [],
            'elapsed_ms': (time.perf_counter() - started) * 1000.0,
        }

    results = []
    passed = 0
    failed = 0
    for case in _parse_regex_unit_tests(source):
        row = dict(case)
        if row.get('error'):
            row.update({'passed': False, 'actual': None, 'actual_values': []})
            failed += 1
            results.append(row)
            continue
        actual_values = [match.group(0) for match in compiled.finditer(row['text'])]
        actual = len(actual_values)
        mode, expected = row['expected']
        if mode == 'minimum':
            ok = actual >= expected
        elif mode == 'values':
            ok = actual_values == expected
        else:
            ok = actual == expected
        row.update({'passed': ok, 'actual': actual, 'actual_values': actual_values})
        if ok:
            passed += 1
        else:
            failed += 1
        results.append(row)
    return {
        'error': '', 'passed': passed, 'failed': failed, 'tests': results,
        'elapsed_ms': (time.perf_counter() - started) * 1000.0,
    }


def _format_regex_unit_test_results(result):
    if (result or {}).get('error'):
        return 'Regex error:\n{}'.format(result.get('error'))
    tests = list((result or {}).get('tests') or [])
    if not tests:
        return ('Add unit tests using: text => count | match | no match | '
                '"full match" | ["match 1", "match 2"]')
    lines = []
    for index, case in enumerate(tests, 1):
        marker = 'PASS' if case.get('passed') else 'FAIL'
        if case.get('error'):
            detail = case.get('error')
        else:
            expected = case.get('expected')
            if expected and expected[0] == 'minimum':
                expected_text = '>= {}'.format(expected[1])
                actual_text = str(case.get('actual'))
            elif expected and expected[0] == 'values':
                expected_text = repr(expected[1])
                actual_text = repr(case.get('actual_values') or [])
            else:
                expected_text = str(expected[1] if expected else '?')
                actual_text = str(case.get('actual'))
            detail = 'expected {}, got {}'.format(expected_text, actual_text)
        lines.append('{}  Test {} (line {})  {}  {}'.format(
            marker, index, case.get('line'), detail, repr(case.get('text'))))
    return '\n'.join(lines)


def _regex_debug_trace(pattern, text, *, ignore_case=False, multiline=False,
                       dotall=False, verbose=False, ascii_only=False):
    """Return a token/prefix trace for Python ``re``.

    Python's stdlib engine does not expose its internal backtracking VM.  This
    debugger therefore provides a deterministic *prefix trace*: each lexical
    regex token is appended, compiled when possible, then searched against the
    current Test String.  It is intentionally labelled an approximation in the
    UI and is useful for locating the token at which a pattern stops matching.
    """
    source = str(pattern or '')
    haystack = str(text or '')
    flags = _regex_flags_value(
        ignore_case=ignore_case, multiline=multiline, dotall=dotall,
        verbose=verbose, ascii_only=ascii_only)
    rows = []
    started = time.perf_counter()
    for step, (start, end, token, description) in enumerate(
            _regex_token_explanations(source), 1):
        prefix = source[:end]
        try:
            compiled = re.compile(prefix, flags)
        except (re.error, TypeError) as exc:
            rows.append({
                'step': step, 'token': token, 'description': description,
                'span': (start, end), 'prefix': prefix, 'state': 'incomplete',
                'match_span': None, 'match_value': None, 'error': str(exc),
            })
            continue
        match = compiled.search(haystack)
        rows.append({
            'step': step, 'token': token, 'description': description,
            'span': (start, end), 'prefix': prefix,
            'state': 'match' if match else 'no-match',
            'match_span': match.span(0) if match else None,
            'match_value': match.group(0) if match else None,
            'error': '',
        })
    return {
        'rows': rows,
        'elapsed_ms': (time.perf_counter() - started) * 1000.0,
    }


def _format_regex_debug_trace(result):
    rows = list((result or {}).get('rows') or [])
    if not rows:
        return 'Enter a regular expression to inspect token-by-token prefix matching.'
    lines = []
    for row in rows:
        state = row.get('state')
        if state == 'match':
            status = 'MATCH {} {}'.format(row.get('match_span'), repr(row.get('match_value')))
        elif state == 'no-match':
            status = 'NO MATCH'
        else:
            status = 'INCOMPLETE · {}'.format(row.get('error') or 'prefix cannot compile yet')
        lines.append('{:>2}. [{:>2}:{:<2}] {:<14} {:<28} {}'.format(
            row.get('step', 0), row.get('span', (0, 0))[0], row.get('span', (0, 0))[1],
            repr(row.get('token')), row.get('description', ''), status))
    return '\n'.join(lines)


def _benchmark_regex(pattern, text, *, iterations=500, ignore_case=False,
                     multiline=False, dotall=False, verbose=False,
                     ascii_only=False):
    """Benchmark repeated ``finditer`` passes without altering UI state."""
    try:
        iterations = max(1, min(5000, int(iterations)))
    except (TypeError, ValueError):
        iterations = 500
    flags = _regex_flags_value(
        ignore_case=ignore_case, multiline=multiline, dotall=dotall,
        verbose=verbose, ascii_only=ascii_only)
    source = str(pattern or '')
    haystack = str(text or '')
    compile_started = time.perf_counter()
    try:
        compiled = re.compile(source, flags)
    except (re.error, TypeError) as exc:
        return {
            'error': str(exc), 'iterations': iterations, 'matches_per_run': 0,
            'compile_ms': (time.perf_counter() - compile_started) * 1000.0,
            'total_ms': 0.0, 'average_ms': 0.0, 'min_ms': 0.0,
            'max_ms': 0.0,
        }
    compile_ms = (time.perf_counter() - compile_started) * 1000.0
    samples = []
    match_count = 0
    for _ in range(iterations):
        started = time.perf_counter()
        count = sum(1 for _match in compiled.finditer(haystack))
        samples.append((time.perf_counter() - started) * 1000.0)
        match_count = count
    total_ms = sum(samples)
    return {
        'error': '', 'iterations': iterations, 'matches_per_run': match_count,
        'compile_ms': compile_ms, 'total_ms': total_ms,
        'average_ms': total_ms / iterations,
        'min_ms': min(samples) if samples else 0.0,
        'max_ms': max(samples) if samples else 0.0,
    }


def _format_regex_benchmark(result):
    if (result or {}).get('error'):
        return 'Regex error:\n{}'.format(result.get('error'))
    return '\n'.join((
        'BENCHMARK RESULT',
        'Iterations       {}'.format(result.get('iterations', 0)),
        'Matches / run    {}'.format(result.get('matches_per_run', 0)),
        'Compile          {}'.format(_format_regex_elapsed(result.get('compile_ms', 0.0))),
        'Average / run    {}'.format(_format_regex_elapsed(result.get('average_ms', 0.0))),
        'Fastest run      {}'.format(_format_regex_elapsed(result.get('min_ms', 0.0))),
        'Slowest run      {}'.format(_format_regex_elapsed(result.get('max_ms', 0.0))),
        'Total            {}'.format(_format_regex_elapsed(result.get('total_ms', 0.0))),
    ))


def _serialize_regex_session(pattern, text, replacement='', unit_tests='', *,
                             extraction_template='', tool_mode='match',
                             export_format='JSON', **flags):
    payload = {
        'schema': 'winux-regex-workbench-v1',
        'pattern': str(pattern or ''),
        'text': str(text or ''),
        'replacement': str(replacement or ''),
        'unit_tests': str(unit_tests or ''),
        'extraction_template': str(extraction_template or ''),
        'tool_mode': str(tool_mode or 'match'),
        'export_format': str(export_format or 'JSON'),
        'flags': {
            'ignore_case': bool(flags.get('ignore_case', False)),
            'multiline': bool(flags.get('multiline', False)),
            'dotall': bool(flags.get('dotall', False)),
            'verbose': bool(flags.get('verbose', False)),
            'ascii_only': bool(flags.get('ascii_only', False)),
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def _deserialize_regex_session(source):
    try:
        payload = json.loads(str(source or ''))
    except (TypeError, ValueError) as exc:
        return {'error': 'Invalid session JSON: {}'.format(exc)}
    if not isinstance(payload, dict) or payload.get('schema') != 'winux-regex-workbench-v1':
        return {'error': 'Unsupported regex workbench session format.'}
    flags = payload.get('flags') if isinstance(payload.get('flags'), dict) else {}
    return {
        'error': '',
        'pattern': str(payload.get('pattern') or ''),
        'text': str(payload.get('text') or ''),
        'replacement': str(payload.get('replacement') or ''),
        'unit_tests': str(payload.get('unit_tests') or ''),
        'extraction_template': str(payload.get('extraction_template') or ''),
        'tool_mode': str(payload.get('tool_mode') or 'match'),
        'export_format': str(payload.get('export_format') or 'JSON'),
        'flags': {
            'ignore_case': bool(flags.get('ignore_case', False)),
            'multiline': bool(flags.get('multiline', False)),
            'dotall': bool(flags.get('dotall', False)),
            'verbose': bool(flags.get('verbose', False)),
            'ascii_only': bool(flags.get('ascii_only', False)),
        },
    }


def _python_regex_code(pattern, text='', replacement='', *, ignore_case=False,
                       multiline=False, dotall=False, verbose=False,
                       ascii_only=False, substitution=False):
    flag_names = []
    if ignore_case:
        flag_names.append('re.IGNORECASE')
    if multiline:
        flag_names.append('re.MULTILINE')
    if dotall:
        flag_names.append('re.DOTALL')
    if verbose:
        flag_names.append('re.VERBOSE')
    if ascii_only:
        flag_names.append('re.ASCII')
    flags_expr = ' | '.join(flag_names) if flag_names else '0'
    lines = [
        'import re',
        '',
        'pattern = re.compile({}, {})'.format(repr(str(pattern or '')), flags_expr),
        'text = {}'.format(repr(str(text or ''))),
    ]
    if substitution:
        lines.extend([
            'replacement = {}'.format(repr(_normalize_regex_replacement(replacement))),
            'result, count = pattern.subn(replacement, text)',
            'print(result)',
            'print("replacements:", count)',
        ])
    else:
        lines.extend([
            'for match in pattern.finditer(text):',
            '    print(match.span(), match.group(0), match.groups(), match.groupdict())',
        ])
    return '\n'.join(lines)


def _regex_token_explanations(pattern):
    """Return regex101-like token explanations without compiling *pattern*.

    This lightweight lexical pass intentionally keeps working for incomplete or
    temporarily-invalid expressions while the user is typing.  Python ``re``
    remains the authority for actual validation/matching.
    """
    source = str(pattern or '')
    items = []
    i = 0
    literal_start = None

    def flush_literal(end):
        nonlocal literal_start
        if literal_start is None or end <= literal_start:
            literal_start = None
            return
        token = source[literal_start:end]
        items.append((literal_start, end, token, 'literal text'))
        literal_start = None

    while i < len(source):
        ch = source[i]
        if ch == '\\':
            flush_literal(i)
            end = min(len(source), i + 2)
            token = source[i:end]
            code = source[i + 1:i + 2]
            if code.isdigit():
                desc = 'backreference to capture group {}'.format(code)
            elif code in _REGEX_ESCAPE_HELP:
                desc = _REGEX_ESCAPE_HELP[code]
            elif code:
                desc = 'escaped literal {}'.format(repr(code))
            else:
                desc = 'escape prefix'
            items.append((i, end, token, desc))
            i = end
            continue
        if ch == '[':
            flush_literal(i)
            j = i + 1
            escaped = False
            while j < len(source):
                current = source[j]
                if escaped:
                    escaped = False
                elif current == '\\':
                    escaped = True
                elif current == ']':
                    j += 1
                    break
                j += 1
            token = source[i:j]
            desc = 'negated character set' if token.startswith('[^') else 'character set'
            items.append((i, j, token, desc))
            i = j
            continue
        if ch == '(':
            flush_literal(i)
            known = (
                ('(?P<', 'named capturing group'),
                ('(?:', 'non-capturing group'),
                ('(?<=', 'positive lookbehind'),
                ('(?<!', 'negative lookbehind'),
                ('(?=', 'positive lookahead'),
                ('(?!', 'negative lookahead'),
                ('(?#', 'comment group'),
                ('(?', 'special/inline-flag group'),
            )
            matched = None
            for prefix, desc in known:
                if source.startswith(prefix, i):
                    matched = (prefix, desc)
                    break
            if matched:
                prefix, desc = matched
                end = i + len(prefix)
                if prefix == '(?P<':
                    close = source.find('>', end)
                    if close >= 0:
                        end = close + 1
                items.append((i, end, source[i:end], desc))
                i = end
            else:
                items.append((i, i + 1, ch, 'capturing group'))
                i += 1
            continue
        if ch == ')':
            flush_literal(i)
            items.append((i, i + 1, ch, 'close group'))
            i += 1
            continue
        if ch in '*+?':
            flush_literal(i)
            end = i + 1
            if end < len(source) and source[end] == '?' and ch in '*+?':
                end += 1
                suffix = ', lazy'
            else:
                suffix = ''
            desc = {'*': '0 or more', '+': '1 or more', '?': '0 or 1'}[ch] + suffix
            items.append((i, end, source[i:end], desc))
            i = end
            continue
        if ch == '{':
            match = re.match(r'\{\d+(?:,\d*)?\}\??', source[i:])
            if match:
                flush_literal(i)
                token = match.group(0)
                desc = 'repetition quantifier' + (', lazy' if token.endswith('?') else '')
                items.append((i, i + len(token), token, desc))
                i += len(token)
                continue
        if ch in '.^$|':
            flush_literal(i)
            desc = {'.': 'any character', '^': 'start anchor', '$': 'end anchor', '|': 'alternation'}[ch]
            items.append((i, i + 1, ch, desc))
            i += 1
            continue
        if literal_start is None:
            literal_start = i
        i += 1
    flush_literal(len(source))
    return items


def _format_regex_explanation(pattern):
    source = str(pattern or '')
    if not source:
        return 'Enter a regular expression to see a token-by-token explanation.'

    lines = []
    group_number = 0
    group_stack = []
    indent = 0

    for start, end, token, description in _regex_token_explanations(source):
        label = '[{}:{}]'.format(start, end)
        lower_desc = str(description).lower()
        prefix = '  ' * max(indent, 0)

        if lower_desc == 'close group':
            indent = max(0, indent - 1)
            prefix = '  ' * max(indent, 0)
            if group_stack:
                group_stack.pop()
            lines.append('{}{}  {}  end group'.format(prefix, label, repr(token)))
            continue

        display_token = repr(token)
        if 'named capturing group' in lower_desc:
            group_number += 1
            name_match = re.search(r'\(\?P<([^>]+)>', token)
            group_name = name_match.group(1) if name_match else 'name'
            lines.append('{}{}  {}  {} named capturing group <{}>'.format(
                prefix, label, display_token, _ordinal(group_number), group_name))
            group_stack.append(('named', group_number))
            indent += 1
            continue
        if lower_desc == 'capturing group':
            group_number += 1
            lines.append('{}{}  {}  {} capturing group'.format(
                prefix, label, display_token, _ordinal(group_number)))
            group_stack.append(('capture', group_number))
            indent += 1
            continue
        if 'non-capturing group' in lower_desc:
            lines.append('{}{}  {}  non-capturing group'.format(prefix, label, display_token))
            group_stack.append(('non-capture', None))
            indent += 1
            continue
        if 'lookahead' in lower_desc or 'lookbehind' in lower_desc:
            lines.append('{}{}  {}  {}'.format(prefix, label, display_token, description))
            group_stack.append(('look', None))
            indent += 1
            continue
        if 'special/inline-flag group' in lower_desc or 'comment group' in lower_desc:
            lines.append('{}{}  {}  {}'.format(prefix, label, display_token, description))
            group_stack.append(('special', None))
            indent += 1
            continue

        lines.append('{}{}  {:<18}  {}'.format(prefix, label, display_token, description))

    return '\n'.join(lines) if lines else 'No tokens.'


def _format_regex_flag_explanation(flags):
    source = str(flags or 'g')
    descriptions = {
        'g': 'global: find all matches instead of stopping after the first',
        'i': 'ignore case: case-insensitive matching',
        'm': 'multiline: ^ and $ also match line boundaries',
        's': 'dotall: . also matches newline characters',
        'x': 'verbose: ignore unescaped pattern whitespace and allow comments',
        'a': r'ASCII: \w, \b, \d and related classes use ASCII semantics',
    }
    lines = ['GLOBAL PATTERN FLAGS']
    for flag in source:
        description = descriptions.get(flag)
        if description:
            lines.append('{} modifier  {}'.format(flag, description))
    return '\n'.join(lines)


def _format_regex_quick_reference(query=''):
    needle = str(query or '').strip().lower()
    sections = []
    for title, rows in REGEX_QUICK_REFERENCE_GROUPS:
        filtered = []
        for token, description in rows:
            if (not needle or needle in token.lower() or
                    needle in description.lower() or needle in title.lower()):
                filtered.append((token, description))
        if not filtered:
            continue
        section_lines = [title.upper()]
        section_lines.extend('{:<16} {}'.format(token, description)
                             for token, description in filtered)
        sections.append('\n'.join(section_lines))
    if not sections:
        return 'No quick-reference entries match {}.'.format(repr(str(query or '').strip()))
    return '\n\n'.join(sections)


def _regex_line_column(text, offset):
    source = str(text or '')
    try:
        position = max(0, min(len(source), int(offset)))
    except (TypeError, ValueError):
        position = 0
    line = source.count('\n', 0, position) + 1
    previous_newline = source.rfind('\n', 0, position)
    column = position + 1 if previous_newline < 0 else position - previous_newline
    return line, column


def _format_regex_selected_match(result, selected_index=0):
    matches = list((result or {}).get('matches') or [])
    if not matches:
        return 'No matches.'
    try:
        index = max(0, min(len(matches) - 1, int(selected_index)))
    except (TypeError, ValueError):
        index = 0
    match = matches[index]
    start, end = match.get('span', (0, 0))
    start_line, start_col = match.get('line_column', (1, 1))
    end_line, end_col = match.get('end_line_column', (start_line, start_col))
    lines = [
        'MATCH {} OF {}'.format(index + 1, len(matches)),
        'Full match   {}-{}   {}'.format(start, end, repr(match.get('value'))),
        'Location     line {}, col {}  →  line {}, col {}'.format(
            start_line, start_col, end_line, end_col),
    ]
    for group in match.get('groups') or []:
        gstart, gend = group.get('span', (-1, -1))
        line_col = group.get('line_column')
        if gstart < 0 or gend < 0:
            lines.append('Group {:<6} unmatched   {}'.format(
                group.get('index'), repr(group.get('value'))))
            continue
        location = ''
        if line_col:
            location = '  line {}, col {}'.format(line_col[0], line_col[1])
        lines.append('Group {:<6} {}-{}{}   {}'.format(
            group.get('index'), gstart, gend, location, repr(group.get('value'))))
    for name, value in (match.get('named') or {}).items():
        lines.append('Named <{}>          {}'.format(name, repr(value)))
    return '\n'.join(lines)


def _format_regex_match_information(result):
    matches = list((result or {}).get('matches') or [])
    if not matches:
        return 'No matches.'
    lines = []
    for number, match in enumerate(matches, 1):
        start, end = match.get('span', (0, 0))
        lines.append('MATCH {}'.format(number))
        lines.append('Full match   {}-{}   {}'.format(start, end, repr(match.get('value'))))
        for group in match.get('groups') or []:
            gstart, gend = group.get('span', (-1, -1))
            lines.append('Group {:<6} {}-{}   {}'.format(
                group.get('index'), gstart, gend, repr(group.get('value'))))
        for name, value in (match.get('named') or {}).items():
            lines.append('Named <{}>          {}'.format(name, repr(value)))
        lines.append('')
    if (result or {}).get('truncated'):
        lines.append('Match list truncated for responsive live editing.')
    return '\n'.join(lines).rstrip()


def _first_regex_pattern(formula):
    """Return the first literal passed to regex(...) in *formula*.

    Formula rules are intentionally Python-like, so ``ast`` is safer than
    trying to peel escaped quotes/backslashes out with another regular
    expression.  Legacy/non-Python selectors simply fall back to an empty
    pattern and the tester remains fully editable.
    """
    source = str(formula or "").strip()
    if not source:
        return ""
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, TypeError, ValueError):
        return ""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "regex":
            continue
        value = node.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
        # Abaqus/Python 2 compatibility path used by some embedded runtimes.
        if hasattr(ast, "Str") and isinstance(value, ast.Str):
            return value.s
    return ""


def _regex_test_text(history_outputs):
    """Build useful default tester text from the active History Output catalog."""
    values = []
    seen = set()
    for item in list(history_outputs or []):
        if isinstance(item, dict):
            value = (item.get("displayName") or item.get("name") or
                     item.get("output") or item.get("label") or "")
        else:
            value = str(item or "")
        value = str(value or "").strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return "\n".join(values)


def _regex_highlight_fragments(text, ranges):
    """Split absolute match spans into line-local fragments for drawing.

    Each returned tuple is ``(line_index, prefix, matched_text)``. Newline
    characters themselves are intentionally not highlighted, matching the
    visual behaviour of browser regex workbenches while still supporting
    DOTALL/multiline matches that cross line boundaries.
    """
    source = str(text or "")
    lines = source.splitlines(True)
    if not lines:
        lines = [""]

    line_records = []
    offset = 0
    for line_index, raw_line in enumerate(lines):
        content = raw_line.rstrip("\r\n")
        line_records.append((line_index, offset, offset + len(content), content))
        offset += len(raw_line)

    fragments = []
    limit = len(source)
    for raw_start, raw_end in list(ranges or []):
        try:
            start = max(0, min(limit, int(raw_start)))
            end = max(start, min(limit, int(raw_end)))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        for line_index, line_start, line_end, content in line_records:
            # No overlap with this line's visible text. Newline-only pieces are
            # skipped because there is no glyph rectangle to paint.
            if end <= line_start:
                break
            if start >= line_end:
                continue
            frag_start = max(start, line_start)
            frag_end = min(end, line_end)
            if frag_end <= frag_start:
                continue
            local_start = frag_start - line_start
            local_end = frag_end - line_start
            fragments.append((
                line_index,
                content[:local_start],
                content[local_start:local_end],
            ))
    return fragments


class _RegexMatchOverlay:
    """Legacy single-viewport markers and shared span normalization.

    The native Check Regex workbench now uses Rich Edit: foreground viewport
    lists do not reliably paint over secondary HWND editors.
    """

    # Low-opacity blue distinguishes complete matches from capture colors.
    FILL = (68, 174, 228, 48)
    BORDER = (0, 130, 200, 100)
    SELECTED_FILL = (68, 174, 228, 85)
    SELECTED_BORDER = (0, 112, 180, 230)
    GROUP_BORDERS = REGEX_GROUP_COLORS
    PAD_X = 7.0
    PAD_Y = 6.0

    def __init__(self, edit_tag):
        self.edit_tag = edit_tag
        self._paint_origin = (0.0, 0.0)
        self._paint_error = ''
        self.layer = None
        self.text = ""
        self.ranges = []
        self.group_ranges = []
        self.selected_index = 0
        self._last_signature = None

    def _ensure_layer(self):
        if self.layer is not None:
            try:
                if dpg.does_item_exist(self.layer):
                    return True
            except Exception:
                pass
            self.delete()
        try:
            # Legacy single-viewport overlay. Native regex dialogs use the
            # dedicated preview below; a viewport foreground list is not a
            # reliable text overlay in a secondary HWND.
            self.layer = dpg.add_viewport_drawlist(front=True)
            return True
        except Exception as exc:
            self._paint_error = str(exc)
            self.layer = None
            return False

    def _clear_native(self):
        layer = self.layer
        if layer is None:
            return
        try:
            if dpg.does_item_exist(layer):
                dpg.delete_item(layer, children_only=True)
        except Exception:
            pass

    @staticmethod
    def _scroll(item, axis):
        getter = getattr(dpg, 'get_{}_scroll'.format(axis), None)
        if not callable(getter):
            return 0.0
        try:
            return max(0.0, float(getter(item) or 0.0))
        except Exception:
            return 0.0

    @staticmethod
    def _measure(value):
        try:
            width, height = dpg.get_text_size(str(value or ""))
            return float(width or 0.0), float(height or 0.0)
        except Exception:
            return float(len(str(value or "")) * 7), 14.0

    @staticmethod
    def _screen_rect(item):
        # item_screen_rect maps through the item's own native HWND.  Under a
        # non-native/single viewport backend it naturally falls back to client
        # coordinates, which are also the viewport drawlist coordinates.
        try:
            from DearUIQt.gui.placement import item_screen_rect
            return item_screen_rect(dpg, item)
        except Exception:
            try:
                x, y = dpg.get_item_rect_min(item)
                width, height = dpg.get_item_rect_size(item)
                return (float(x), float(y), float(x) + float(width),
                        float(y) + float(height))
            except Exception:
                return None

    def set_matches(self, text, ranges, group_ranges=None, selected_index=0):
        self.text = str(text or "")
        normalized = []
        for span in list(ranges or []):
            try:
                start, end = span
                start, end = int(start), int(end)
            except (TypeError, ValueError):
                continue
            if end >= start and start >= 0:
                normalized.append((start, end))
        self.ranges = normalized
        normalized_groups = []
        for raw in list(group_ranges or []):
            try:
                start, end, group_index = raw
                start, end, group_index = int(start), int(end), int(group_index)
            except (TypeError, ValueError):
                continue
            if end >= start and start >= 0:
                normalized_groups.append((start, end, group_index))
        self.group_ranges = normalized_groups
        self.selected_index = (max(0, min(len(normalized) - 1, int(selected_index or 0)))
                               if normalized else 0)
        self._last_signature = None
        self.refresh(force=True)

    def clear(self):
        self.text = ""
        self.ranges = []
        self.group_ranges = []
        self.selected_index = 0
        self._last_signature = None
        self._clear_native()
        try:
            if self.layer is not None and dpg.does_item_exist(self.layer):
                dpg.configure_item(self.layer, show=False)
        except Exception:
            pass

    def _draw_rectangle(self, first, second, **options):
        ox, oy = self._paint_origin
        return dpg.draw_rectangle((first[0] - ox, first[1] - oy),
                                  (second[0] - ox, second[1] - oy), **options)

    def _draw_line(self, first, second, **options):
        ox, oy = self._paint_origin
        return dpg.draw_line((first[0] - ox, first[1] - oy),
                             (second[0] - ox, second[1] - oy), **options)

    def refresh(self, force=False):
        if not self.ranges:
            self._clear_native()
            try:
                if self.layer is not None and dpg.does_item_exist(self.layer):
                    dpg.configure_item(self.layer, show=False)
            except Exception:
                pass
            return False
        try:
            current = self.edit_tag
            while current:
                if not dpg.does_item_exist(current) or not dpg.is_item_shown(current):
                    self._clear_native()
                    self._last_signature = None
                    return False
                parent = dpg.get_item_parent(current)
                current = parent if isinstance(parent, (int, str)) else None
        except Exception:
            return False

        rect = self._screen_rect(self.edit_tag)
        if rect is None:
            return False
        left, top, right, bottom = map(float, rect)
        width, height = right - left, bottom - top
        if width <= 2 or height <= 2:
            return False

        scroll_x = self._scroll(self.edit_tag, 'x')
        scroll_y = self._scroll(self.edit_tag, 'y')
        signature = (left, top, right, bottom, scroll_x, scroll_y,
                     self.text, tuple(self.ranges), tuple(self.group_ranges), self.selected_index)
        if not force and signature == self._last_signature:
            return True
        self._last_signature = signature
        if not self._ensure_layer():
            return False
        try:
            dpg.configure_item(self.layer, show=True)
            self._paint_origin = (0.0, 0.0)
        except Exception:
            return False
        self._clear_native()

        _, measured_line_height = self._measure("Ag")
        line_height = max(13.0, measured_line_height)
        clip_left = left + 1.0
        clip_top = top + 1.0
        clip_right = right - 2.0
        clip_bottom = bottom - 2.0
        painted = 0

        for match_index, match_range in enumerate(self.ranges):
            selected = match_index == self.selected_index
            fill = self.SELECTED_FILL if selected else self.FILL
            border = self.SELECTED_BORDER if selected else self.BORDER
            thickness = 1.8 if selected else 1.0
            start, end = match_range
            if end == start:
                line_index, prefix = _regex_zero_width_fragment(self.text, start)
                prefix_width, _ = self._measure(prefix)
                x = left + self.PAD_X + prefix_width - scroll_x
                y1 = top + self.PAD_Y + line_index * line_height - scroll_y
                y2 = y1 + line_height
                rx = min(max(x, clip_left), clip_right)
                ry1, ry2 = max(y1, clip_top), min(y2, clip_bottom)
                if ry2 > ry1:
                    try:
                        self._draw_line(
                            (rx, ry1), (rx, ry2), parent=self.layer,
                            color=border, thickness=3.0 if selected else 2.0)
                        painted += 1
                    except Exception:
                        pass
                continue
            for line_index, prefix, fragment in _regex_highlight_fragments(self.text, [match_range]):
                prefix_width, _ = self._measure(prefix)
                fragment_width, _ = self._measure(fragment)
                x1 = left + self.PAD_X + prefix_width - scroll_x
                y1 = top + self.PAD_Y + line_index * line_height - scroll_y
                x2 = x1 + max(2.0, fragment_width)
                y2 = y1 + line_height
                rx1, ry1 = max(x1, clip_left), max(y1, clip_top)
                rx2, ry2 = min(x2, clip_right), min(y2, clip_bottom)
                if rx2 <= rx1 or ry2 <= ry1:
                    continue
                try:
                    self._draw_rectangle(
                        (rx1, ry1), (rx2, ry2), parent=self.layer,
                        color=border, fill=fill, rounding=1.5, thickness=thickness)
                    painted += 1
                except Exception:
                    pass
        # Captures share the syntax preview's group palette. A light tint plus
        # an outline keeps both the native glyphs and nested groups readable.
        for raw_start, raw_end, group_index in self.group_ranges:
            if raw_end == raw_start:
                line_index, prefix = _regex_zero_width_fragment(self.text, raw_start)
                prefix_width, _ = self._measure(prefix)
                x = left + self.PAD_X + prefix_width - scroll_x
                y1 = top + self.PAD_Y + line_index * line_height - scroll_y
                y2 = y1 + line_height
                rx = min(max(x, clip_left), clip_right)
                ry1, ry2 = max(y1, clip_top), min(y2, clip_bottom)
                color = self.GROUP_BORDERS[(max(1, group_index) - 1) % len(self.GROUP_BORDERS)]
                if ry2 > ry1:
                    try:
                        self._draw_line((rx, ry1), (rx, ry2), parent=self.layer,
                                      color=color, thickness=2.0)
                    except Exception:
                        pass
                continue
            for line_index, prefix, fragment in _regex_highlight_fragments(
                    self.text, [(raw_start, raw_end)]):
                prefix_width, _ = self._measure(prefix)
                fragment_width, _ = self._measure(fragment)
                x1 = left + self.PAD_X + prefix_width - scroll_x
                y1 = top + self.PAD_Y + line_index * line_height - scroll_y
                x2 = x1 + max(2.0, fragment_width)
                y2 = y1 + line_height
                rx1, ry1 = max(x1, clip_left), max(y1, clip_top)
                rx2, ry2 = min(x2, clip_right), min(y2, clip_bottom)
                if rx2 <= rx1 or ry2 <= ry1:
                    continue
                color = self.GROUP_BORDERS[(max(1, group_index) - 1) % len(self.GROUP_BORDERS)]
                try:
                    self._draw_rectangle(
                        (rx1, ry1), (rx2, ry2), parent=self.layer, color=color,
                        fill=tuple(color[:3]) + (32,), rounding=1.5, thickness=2.0)
                except Exception:
                    pass
        return painted > 0

    def delete(self):
        layer, self.layer = self.layer, None
        self._last_signature = None
        try:
            if layer is not None and dpg.does_item_exist(layer):
                dpg.delete_item(layer)
        except Exception:
            pass


class RegexTesterDialog(QtDialog):
    """Regex101-inspired live Python regex workbench owned by Reference Chart."""

    LIVE_DEBOUNCE_MS = 30
    OVERLAY_SYNC_MS = 80
    MAX_LIVE_MATCHES = 500

    def __init__(self, view, pattern="", text="", parent=None):
        self._finished = False
        self._live_after = None
        self._overlay_after = None
        self._match_overlay = None
        self._last_live_result = {"matches": []}
        self._selected_match_index = 0
        self._match_information_view = 'All matches'
        self._tool_mode = 'match'
        self._mode_selector_guard = False
        self._native_regex_fields = []
        self._native_after = None
        self._regex_error_position = None
        super().__init__(view, "Check Regex", 1180, 760, modal=True, parent=parent)
        self.setMinimumSize(980, 640)
        self.preferred_size = (1180, 760)

        self._pattern_header = self.own_widget(QGridLayout(
            3, column_widths=(None, 285, 82), parent=self.contentWidget(),
            after=self.view.after, height=24))
        QLabel("REGULAR EXPRESSION", parent=self._pattern_header.cell(0, 0))
        self.pattern_status = self.status_text(
            "0 matches · 0 tokens · 0 groups · 0 µs",
            parent=self._pattern_header.cell(0, 1).tag)
        QLabel("Python", parent=self._pattern_header.cell(0, 2))

        # regex101-like /pattern/flags composition.  The Python editor value
        # remains only the raw pattern, while the chrome exposes regex syntax
        # and active modifiers without polluting the formula pattern itself.
        self._regex_bar = self.own_widget(QGridLayout(
            4, column_widths=(18, None, 18, 82), parent=self.contentWidget(),
            after=self.view.after, height=30))
        QLabel("/", parent=self._regex_bar.cell(0, 0))
        self.pattern_edit = self._rich_edit(
            pattern or "", parent=self._regex_bar.cell(0, 1).tag, width=-1,
            callback=self._input_changed)
        QLabel("/", parent=self._regex_bar.cell(0, 2))
        self.pattern_flags = self.status_text("g", parent=self._regex_bar.cell(0, 3).tag)

        self._flags_grid = self.own_widget(QGridLayout(
            7, column_widths=(54, 42, 42, 42, 42, 42, None),
            parent=self.contentWidget(), after=self.view.after, height=26))
        QLabel("FLAGS", parent=self._flags_grid.cell(0, 0))
        self.ignore_case = self.checkbox("i", checked=False,
                                         parent=self._flags_grid.cell(0, 1).tag)
        self.multiline = self.checkbox("m", checked=False,
                                       parent=self._flags_grid.cell(0, 2).tag)
        self.dotall = self.checkbox("s", checked=False,
                                    parent=self._flags_grid.cell(0, 3).tag)
        self.verbose = self.checkbox("x", checked=False,
                                     parent=self._flags_grid.cell(0, 4).tag)
        self.ascii_only = self.checkbox("a", checked=False,
                                        parent=self._flags_grid.cell(0, 5).tag)
        flag_help = (
            (self.ignore_case, "i · IGNORECASE"),
            (self.multiline, "m · MULTILINE"),
            (self.dotall, "s · DOTALL"),
            (self.verbose, "x · VERBOSE"),
            (self.ascii_only, "a · ASCII"),
        )
        for control, tooltip in flag_help:
            wrapper = self.control_wrapper(control)
            if wrapper is not None:
                wrapper.setToolTip(tooltip)
                wrapper.toggled.connect(self._flag_changed, receiver=self)

        # regex101-style workbench: edit/test on the left, inspect explanation,
        # matches and reference material on the right.  The grid owns layout;
        # the native test editor remains a single widget so highlighting never
        # introduces extra layout rows.
        self._workspace = self.own_widget(QGridLayout(
            2, column_widths=(None, 360), parent=self.contentWidget(),
            after=self.view.after, height=-1, vertical_dividers=True))
        self._test_panel_widget = self.own_widget(QFrame(
            parent=self._workspace.cell(0, 0), width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True))
        self._inspector_panel_widget = self.own_widget(QFrame(
            parent=self._workspace.cell(0, 1), width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=False,
            no_scroll_with_mouse=False))

        # Compact regex101-style mode strip.  Function and tool selectors
        # replace two rows of push buttons so the Test String keeps the visual
        # priority and the workbench scales better on smaller screens.
        self._mode_bar = self.own_widget(QGridLayout(
            4, column_widths=(58, None, 42, None),
            parent=self._test_panel_widget, after=self.view.after, height=28))
        QLabel("Function", parent=self._mode_bar.cell(0, 0))
        self.function_selector = self.combo(
            ("Match", "Substitution", "Extraction", "Unit Tests"),
            parent=self._mode_bar.cell(0, 1).tag, default_value="Match",
            width=-1, callback=self._function_mode_changed)
        QLabel("Tools", parent=self._mode_bar.cell(0, 2))
        self.tools_selector = self.combo(
            ("Tools...", "Code Generator", "Regex Debugger", "Regex Converter",
             "Export Matches", "Benchmark", "Format Regex"),
            parent=self._mode_bar.cell(0, 3).tag, default_value="Tools...",
            width=-1, callback=self._tools_mode_changed)
        self._test_header = self.own_widget(QGridLayout(
            3, column_widths=(None, 150, 140), parent=self._test_panel_widget,
            after=self.view.after, height=24))
        self._test_title_label = QLabel("TEST STRING", parent=self._test_header.cell(0, 0))
        self.input_position = self.status_text("1 line · 0 chars", parent=self._test_header.cell(0, 1).tag)
        self.line_column_status = self.status_text(
            "Line 1, column 1", parent=self._test_header.cell(0, 2).tag)

        # Compatibility attributes retained for older callers; navigation is
        # now selector-driven rather than one button per mode.
        self.match_mode_button = None
        self.substitution_mode_button = None
        self.extraction_mode_button = None
        self.unit_tests_mode_button = None
        self.code_mode_button = None
        self.debug_mode_button = None
        self.converter_mode_button = None
        self.export_mode_button = None
        self.benchmark_mode_button = None
        self.format_mode_button = None
        self._match_workspace_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True, no_scroll_with_mouse=True))
        self._subject_toolbar = self.own_widget(QGridLayout(
            3, column_widths=(None, 72, 58), parent=self._match_workspace_widget,
            after=self.view.after, height=28))
        self._subject_hint = self.status_text('Type or paste text to test.',
            parent=self._subject_toolbar.cell(0, 0).tag)
        self.subject_example_button = self.action('Example', self._load_regex_example, role='secondary',
            parent=self._subject_toolbar.cell(0, 1).tag, width=68, height=24)
        self.control_wrapper(self.subject_example_button).setToolTip(
            'Replace pattern and test text with a capture-group example. Ctrl+Z in each editor to undo.')
        self.subject_clear_button = self.action('Clear', self._clear_regex_subject, role='secondary',
            parent=self._subject_toolbar.cell(0, 2).tag, width=54, height=24)
        self._test_editor_grid = self.own_widget(QGridLayout(
            2, column_widths=(44, None), parent=self._match_workspace_widget,
            after=self.view.after, height=-1, vertical_dividers=True))
        self.line_numbers_edit = self._rich_edit(
            _regex_line_numbers(text), parent=self._test_editor_grid.cell(0, 0).tag,
            width=-1, height=-1, readonly=True, multiline=True, scrollbars=False, focusable=False,
            alignment='center')
        self.text_edit = self._rich_edit(
            text or "", parent=self._test_editor_grid.cell(0, 1).tag, width=-1, height=-1,
            multiline=True,
            callback=self._input_changed)

        # Regex101-style auxiliary workspaces.  Only one left-side workspace is
        # visible at a time, so enabling substitution/unit tests never adds an
        # extra row below the expanding Test String editor.
        self._substitution_panel_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False))
        self._substitution_header = self.own_widget(QGridLayout(
            2, column_widths=(None, 170), parent=self._substitution_panel_widget,
            after=self.view.after, height=26))
        QLabel("SUBSTITUTION", parent=self._substitution_header.cell(0, 0))
        self.substitution_status = self.status_text(
            "0 replacements", parent=self._substitution_header.cell(0, 1).tag)
        QLabel("Replacement", parent=self._substitution_panel_widget)
        self.replacement_edit = self.line_edit(
            "$&", parent=self._substitution_panel_widget.tag, width=-1,
            callback=self._replacement_changed)
        self.note(
            "Replacement supports regex101 tokens $1, ${name}, $& and Python \\g<name>.",
            parent=self._substitution_panel_widget.tag, wrap=620)
        QLabel("SUBSTITUTION RESULT", parent=self._substitution_panel_widget)
        self.substitution_result_edit = self.plain_text_edit(
            text or "", parent=self._substitution_panel_widget.tag,
            width=-1, height=-1, readonly=True)

        self._extraction_panel_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False))
        self._extraction_header = self.own_widget(QGridLayout(
            2, column_widths=(None, 170), parent=self._extraction_panel_widget,
            after=self.view.after, height=26))
        QLabel("EXTRACTION", parent=self._extraction_header.cell(0, 0))
        self.extraction_status = self.status_text(
            "0 matches", parent=self._extraction_header.cell(0, 1).tag)
        QLabel("Extraction template", parent=self._extraction_panel_widget)
        self.extraction_template_edit = self.line_edit(
            "$&\n", parent=self._extraction_panel_widget.tag, width=-1,
            callback=self._extraction_changed)
        self.note(
            r"Only matched content is emitted. Template supports $1, ${name}, $& and Python \g<name>.",
            parent=self._extraction_panel_widget.tag, wrap=680)
        QLabel("EXTRACTION RESULT", parent=self._extraction_panel_widget)
        self.extraction_result_edit = self.plain_text_edit(
            "", parent=self._extraction_panel_widget.tag,
            width=-1, height=-1, readonly=True)

        self._unit_tests_panel_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False))
        self._unit_tests_header = self.own_widget(QGridLayout(
            2, column_widths=(None, 190), parent=self._unit_tests_panel_widget,
            after=self.view.after, height=26))
        QLabel("UNIT TESTS", parent=self._unit_tests_header.cell(0, 0))
        self.unit_tests_status = self.status_text(
            "0 passed · 0 failed", parent=self._unit_tests_header.cell(0, 1).tag)
        self.note(
            "One case per line: text => count | match | no match | \"full match\" | [\"m1\", \"m2\"].",
            parent=self._unit_tests_panel_widget.tag, wrap=620)
        self._unit_tests_grid = self.own_widget(QGridLayout(
            2, column_widths=(None, None), parent=self._unit_tests_panel_widget,
            after=self.view.after, height=-1, vertical_dividers=True))
        self.unit_tests_edit = self.plain_text_edit(
            "", parent=self._unit_tests_grid.cell(0, 0).tag,
            width=-1, height=-1, callback=self._unit_tests_changed)
        self.unit_tests_result_edit = self.plain_text_edit(
            "Add unit tests using: text => expected count",
            parent=self._unit_tests_grid.cell(0, 1).tag,
            width=-1, height=-1, readonly=True)

        self._code_panel_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False))
        self._code_header = self.own_widget(QGridLayout(
            5, column_widths=(None, 126, 62, 68, 68), parent=self._code_panel_widget,
            after=self.view.after, height=28))
        QLabel("CODE GENERATOR", parent=self._code_header.cell(0, 0))
        self.code_use_substitution = self.checkbox(
            "Substitution", checked=False, parent=self._code_header.cell(0, 1).tag)
        code_sub_wrapper = self.control_wrapper(self.code_use_substitution)
        if code_sub_wrapper is not None:
            code_sub_wrapper.toggled.connect(self._code_generator_changed, receiver=self)
        self.copy_python_button = self.action(
            "Copy", self._copy_python_code, role="secondary",
            parent=self._code_header.cell(0, 2).tag, width=58, height=24)
        self.export_session_button = self.action(
            "Export", self._copy_regex_session, role="secondary",
            parent=self._code_header.cell(0, 3).tag, width=64, height=24)
        self.import_session_button = self.action(
            "Import", self._paste_regex_session, role="secondary",
            parent=self._code_header.cell(0, 4).tag, width=64, height=24)
        self.note(
            "Generated for Python re using the current pattern, flags and Test String.",
            parent=self._code_panel_widget.tag, wrap=620)
        self.code_edit = self.plain_text_edit(
            "", parent=self._code_panel_widget.tag, width=-1, height=-1, readonly=True)

        self._debug_panel_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False))
        self._debug_header = self.own_widget(QGridLayout(
            2, column_widths=(None, 180), parent=self._debug_panel_widget,
            after=self.view.after, height=28))
        QLabel("REGEX DEBUGGER", parent=self._debug_header.cell(0, 0))
        self.debug_status = self.status_text(
            "Python prefix trace", parent=self._debug_header.cell(0, 1).tag)
        self.note(
            "Python re does not expose its internal backtracking VM. This trace compiles each token prefix and shows where matching stops.",
            parent=self._debug_panel_widget.tag, wrap=620)
        self.debug_edit = self.plain_text_edit(
            "Enter a regular expression to inspect token-by-token prefix matching.",
            parent=self._debug_panel_widget.tag, width=-1, height=-1, readonly=True)

        self._benchmark_panel_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False))
        self._benchmark_header = self.own_widget(QGridLayout(
            4, column_widths=(None, 76, 88, 74), parent=self._benchmark_panel_widget,
            after=self.view.after, height=30))
        QLabel("BENCHMARK", parent=self._benchmark_header.cell(0, 0))
        QLabel("Iterations", parent=self._benchmark_header.cell(0, 1))
        self.benchmark_iterations = self.line_edit(
            "500", parent=self._benchmark_header.cell(0, 2).tag, width=82)
        self.run_benchmark_button = self.action(
            "Run", self._run_regex_benchmark, role="primary",
            parent=self._benchmark_header.cell(0, 3).tag, width=68, height=24)
        self.note(
            "Runs repeated Python re.finditer passes on the current Test String. Maximum 5000 iterations.",
            parent=self._benchmark_panel_widget.tag, wrap=620)
        self.benchmark_edit = self.plain_text_edit(
            "Press Run to benchmark the current expression.",
            parent=self._benchmark_panel_widget.tag, width=-1, height=-1, readonly=True)

        self._converter_panel_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False))
        self._converter_header = self.own_widget(QGridLayout(
            3, column_widths=(None, 150, 70), parent=self._converter_panel_widget,
            after=self.view.after, height=28))
        QLabel("REGEX CONVERTER", parent=self._converter_header.cell(0, 0))
        self.converter_target = self.combo(
            ("JavaScript",), parent=self._converter_header.cell(0, 1).tag,
            default_value="JavaScript", width=-1, callback=self._converter_changed)
        self.copy_converter_button = self.action(
            "Copy", self._copy_converter_result, role="secondary",
            parent=self._converter_header.cell(0, 2).tag, width=64, height=24)
        self.note(
            "Best-effort Python re → JavaScript conversion. Unsupported constructs are reported instead of silently rewritten.",
            parent=self._converter_panel_widget.tag, wrap=680)
        self.converter_edit = self.plain_text_edit(
            "", parent=self._converter_panel_widget.tag, width=-1, height=-1, readonly=True)

        self._export_panel_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False))
        self._export_header = self.own_widget(QGridLayout(
            3, column_widths=(None, 150, 70), parent=self._export_panel_widget,
            after=self.view.after, height=28))
        QLabel("EXPORT MATCHES", parent=self._export_header.cell(0, 0))
        self.export_format = self.combo(
            ("JSON", "JSON Lines", "CSV", "Plain Text"),
            parent=self._export_header.cell(0, 1).tag, default_value="JSON",
            width=-1, callback=self._export_format_changed)
        self.copy_export_button = self.action(
            "Copy", self._copy_export_matches, role="secondary",
            parent=self._export_header.cell(0, 2).tag, width=64, height=24)
        self.export_edit = self.plain_text_edit(
            "[]", parent=self._export_panel_widget.tag, width=-1, height=-1, readonly=True)

        self._format_panel_widget = self.own_widget(QFrame(
            parent=self._test_panel_widget, width=-1, height=-1,
            frame_shape=QFrame.NoFrame, no_scrollbar=True,
            no_scroll_with_mouse=True, show=False))
        self._format_header = self.own_widget(QGridLayout(
            2, column_widths=(None, 70), parent=self._format_panel_widget,
            after=self.view.after, height=28))
        QLabel("FORMAT REGEX", parent=self._format_header.cell(0, 0))
        self.copy_format_button = self.action(
            "Copy", self._copy_formatted_regex, role="secondary",
            parent=self._format_header.cell(0, 1).tag, width=64, height=24)
        self.note(
            "Structural formatting view. It does not modify the live pattern or its matching semantics.",
            parent=self._format_panel_widget.tag, wrap=680)
        self.format_edit = self.plain_text_edit(
            _format_regex_structure(pattern), parent=self._format_panel_widget.tag,
            width=-1, height=-1, readonly=True)

        self._explanation_header = self.own_widget(QGridLayout(
            2, column_widths=(None, 28), parent=self._inspector_panel_widget,
            after=self.view.after, height=26))
        QLabel("EXPLANATION", parent=self._explanation_header.cell(0, 0))
        self.explanation_toggle = self.action(
            "-", self._toggle_explanation, role="secondary",
            parent=self._explanation_header.cell(0, 1).tag, width=24, height=22)
        self.explanation_edit = self._rich_edit(
            _format_regex_explanation(pattern), parent=self._inspector_panel_widget.tag,
            width=-1, height=155, readonly=True, multiline=True, wrap=True)

        self._match_header = self.own_widget(QGridLayout(
            3, column_widths=(None, 124, 28), parent=self._inspector_panel_widget,
            after=self.view.after, height=26))
        QLabel("MATCH INFORMATION", parent=self._match_header.cell(0, 0))
        self.match_view_selector = self.combo(
            ('All matches', 'Selected only'), parent=self._match_header.cell(0, 1).tag,
            default_value='All matches', width=-1, callback=self._match_view_changed)
        self.match_toggle = self.action(
            "-", self._toggle_match_information, role="secondary",
            parent=self._match_header.cell(0, 2).tag, width=24, height=22)
        self._match_navigation = self.own_widget(QGridLayout(
            6, column_widths=(52, 52, None, 44, 36, 52), parent=self._inspector_panel_widget,
            after=self.view.after, height=28))
        self.match_prev_button = self.action(
            "Prev", self._previous_match, role="secondary",
            parent=self._match_navigation.cell(0, 0).tag, width=48, height=24)
        self.match_next_button = self.action(
            "Next", self._next_match, role="secondary",
            parent=self._match_navigation.cell(0, 1).tag, width=48, height=24)
        self.match_position = self.status_text(
            "0 / 0", parent=self._match_navigation.cell(0, 2).tag)
        self.match_jump_edit = self.line_edit('', parent=self._match_navigation.cell(0, 3).tag,
            width=-1, placeholder='#')
        self.control_wrapper(self.match_jump_edit).setToolTip('Match number (1-based), then Go.')
        self.match_jump_button = self.action('Go', self._jump_to_match, role='secondary',
            parent=self._match_navigation.cell(0, 4).tag, width=32, height=24)
        self.copy_match_button = self.action(
            "Copy", self._copy_selected_match, role="secondary",
            parent=self._match_navigation.cell(0, 5).tag, width=48, height=24)
        self.results_edit = self._rich_edit(
            "No matches.", parent=self._inspector_panel_widget.tag,
            width=-1, height=185, readonly=True, multiline=True)

        self._quick_reference_header = self.own_widget(QGridLayout(
            2, column_widths=(None, 28), parent=self._inspector_panel_widget,
            after=self.view.after, height=26))
        QLabel("QUICK REFERENCE", parent=self._quick_reference_header.cell(0, 0))
        self.quick_reference_toggle = self.action(
            "-", self._toggle_quick_reference, role="secondary",
            parent=self._quick_reference_header.cell(0, 1).tag, width=24, height=22)
        self.quick_reference_search = self.line_edit(
            "", parent=self._inspector_panel_widget.tag, width=-1,
            placeholder="Search reference...", callback=self._quick_reference_changed)
        self.quick_reference_edit = self.plain_text_edit(
            _format_regex_quick_reference(), parent=self._inspector_panel_widget.tag,
            width=-1, height=150, readonly=True)

        self.summary = self.status_text(
            "Live matching: edit the expression or test string.", parent=self.content)
        self.button_box([
            ("Close", self.destroy, "secondary", True),
        ], status_item=self.summary)
        self.view.after(1, self.focus_control, self.pattern_edit)
        self._schedule_live_test(delay=1)
        if self._native_regex_fields:
            self.after_first_present(self._sync_native_regex_fields)

    def _rich_edit(self, value='', *, parent, width=-1, height=28,
                   multiline=False, readonly=False, callback=None, scrollbars=True, focusable=True, wrap=False,
                   alignment='left'):
        if os.name != 'nt' or self._native_window_backend is None:
            factory = self.plain_text_edit if multiline else self.line_edit
            options = dict(parent=parent, width=width, readonly=readonly, callback=callback)
            if multiline:
                options['height'] = height
            return factory(value, **options)
        from ...ui.components.regex_rich_edit import RegexRichEdit
        widget = self.own_widget(RegexRichEdit(value, parent=self._qt_parent(parent),
            owner_handle=lambda: self._native_window_backend.winId(self.tag),
            after=self.view.after, width=width, height=height,
            multiline=multiline, readonly=readonly, callback=callback, scrollbars=scrollbars, wrap=wrap,
            alignment=alignment))
        self._control_wrappers[widget.tag] = widget
        if focusable:
            self._remember_focusable(widget.tag)
        self._native_regex_fields.append(widget)
        return widget.tag

    def _sync_native_regex_fields(self):
        self._native_after = None
        if self._finished:
            return
        for field in self._native_regex_fields:
            action = field.sync_native(hidden=self._tool_mode != 'match' and
                                       field.tag in (self.text_edit, self.line_numbers_edit))
            if action is None:
                continue
            if action[0] == 'escape':
                self.reject()
                return
            # Continue the existing dialog tab order from the native field.
            def shown(tag):
                current = tag
                while current:
                    if not dpg.is_item_shown(current):
                        return False
                    current = dpg.get_item_parent(current)
                return True
            candidates = [tag for tag in self._focus_order if self._item_is_focusable(tag) and shown(tag)]
            if field.tag in candidates:
                index = (candidates.index(field.tag) + (-1 if action[1] else 1)) % len(candidates)
                field._user32.SetFocus(field._owner)
                self.focus_control(candidates[index])
            elif candidates:
                field._user32.SetFocus(field._owner)
                self.focus_control(candidates[-1 if action[1] else 0])
        self._refresh_inline_colors()
        self._sync_line_number_scroll()
        self._update_subject_status()
        self._native_after = self.view.after(40, self._sync_native_regex_fields)

    def _refresh_inline_colors(self):
        fields = getattr(self, '_native_regex_fields', [])
        if not fields:
            return
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        verbose = bool(self.control_value(self.verbose, False))
        result = self._last_live_result or {'matches': []}
        text = str(self.control_value(self.text_edit, '') or '')
        info = str(self.control_value(self.results_edit, '') or '')
        explanation = str(self.control_value(self.explanation_edit, '') or '')
        key = (pattern, verbose, getattr(self, '_regex_error_position', None), text,
               id(result), self._selected_match_index, info, explanation,
               tuple(field.hwnd for field in fields))
        if key == getattr(self, '_inline_color_key', None):
            return
        pattern_spans = regex_pattern_spans(pattern, verbose=verbose,
            error_position=getattr(self, '_regex_error_position', None))
        painted = self.control_wrapper(self.pattern_edit).set_colors(pattern_spans)
        painted &= self.control_wrapper(self.text_edit).set_colors(
            regex_subject_spans(result, self._selected_match_index))
        painted &= self.control_wrapper(self.results_edit).set_colors(
            regex_inspector_spans(info, result.get('named_groups')))
        # Color the pattern repeated at the top of Explanation, like regex101.
        painted &= self.control_wrapper(self.explanation_edit).set_colors(
            regex_explanation_spans(pattern, explanation, verbose=verbose,
                error_position=getattr(self, '_regex_error_position', None))
            if explanation.startswith(pattern + '\n') else [])
        painted &= self.control_wrapper(self.line_numbers_edit).set_colors([],
            default_foreground=(110, 116, 124))
        if painted:
            self._inline_color_key = key

    @classmethod
    def evaluate(cls, pattern, text, *, ignore_case=False, multiline=False,
                 dotall=False, verbose=False, ascii_only=False):
        """Compile/run Python ``re`` and return UI-neutral live-workbench data."""
        flags = 0
        if ignore_case:
            flags |= re.IGNORECASE
        if multiline:
            flags |= re.MULTILINE
        if dotall:
            flags |= re.DOTALL
        if verbose:
            flags |= re.VERBOSE
        if ascii_only:
            flags |= re.ASCII

        started = time.perf_counter()
        try:
            compiled = re.compile(str(pattern or ""), flags)
        except (re.error, TypeError) as exc:
            location = _regex_error_location(exc, pattern)
            return {
                "error": str(exc), "matches": [], "group_count": 0,
                "named_groups": {}, "elapsed_ms": (time.perf_counter() - started) * 1000.0,
                "truncated": False,
                "error_position": location.get("position"),
                "error_line": location.get("line"),
                "error_column": location.get("column"),
            }

        matches = []
        truncated = False
        for match in compiled.finditer(str(text or "")):
            if len(matches) >= cls.MAX_LIVE_MATCHES:
                truncated = True
                break
            groups = []
            for index, value in enumerate(match.groups(), 1):
                try:
                    span = match.span(index)
                except (IndexError, ValueError):
                    span = (-1, -1)
                groups.append({
                    "index": index, "value": value, "span": span,
                    "line_column": (_regex_line_column(text, span[0])
                                      if span[0] >= 0 else None),
                })
            named = {}
            for name, index in sorted(compiled.groupindex.items(), key=lambda pair: pair[1]):
                named[name] = match.group(name)
            full_span = match.span(0)
            matches.append({
                "value": match.group(0),
                "span": full_span,
                "line_column": _regex_line_column(text, full_span[0]),
                "end_line_column": _regex_line_column(text, full_span[1]),
                "groups": groups,
                "named": named,
            })
        return {
            "error": "",
            "matches": matches,
            "group_count": compiled.groups,
            "named_groups": dict(compiled.groupindex),
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            "truncated": truncated,
        }

    def _flag_state(self):
        return {
            "ignore_case": bool(self.control_value(self.ignore_case, False)),
            "multiline": bool(self.control_value(self.multiline, False)),
            "dotall": bool(self.control_value(self.dotall, False)),
            "verbose": bool(self.control_value(self.verbose, False)),
            "ascii_only": bool(self.control_value(self.ascii_only, False)),
        }

    def _active_flag_letters(self):
        return _regex_flag_letters(**self._flag_state())

    def _function_mode_changed(self, _sender=None, value=None, _user_data=None):
        if self._mode_selector_guard or self._finished:
            return False
        selected = str(value or self.control_value(self.function_selector, "Match") or "Match")
        mode = {
            "Match": "match",
            "Substitution": "substitution",
            "Extraction": "extraction",
            "Unit Tests": "unit_tests",
        }.get(selected, "match")
        return self._set_tool_mode(mode)

    def _tools_mode_changed(self, _sender=None, value=None, _user_data=None):
        if self._mode_selector_guard or self._finished:
            return False
        selected = str(value or self.control_value(self.tools_selector, "Tools...") or "Tools...")
        mode = {
            "Code Generator": "code",
            "Regex Debugger": "debug",
            "Regex Converter": "converter",
            "Export Matches": "export",
            "Benchmark": "benchmark",
            "Format Regex": "format",
        }.get(selected)
        return False if mode is None else self._set_tool_mode(mode)

    def _set_tool_mode(self, mode):
        mode = str(mode or 'match')
        supported = (
            'match', 'substitution', 'extraction', 'unit_tests',
            'code', 'debug', 'converter', 'export', 'benchmark', 'format',
        )
        if mode not in supported:
            mode = 'match'
        self._tool_mode = mode
        if mode != 'match':
            overlay = getattr(self, '_match_overlay', None)
            if overlay is not None:
                overlay.clear()
            self._cancel_after('_overlay_after')
        function_labels = {
            'match': 'Match', 'substitution': 'Substitution',
            'extraction': 'Extraction', 'unit_tests': 'Unit Tests',
        }
        tool_labels = {
            'code': 'Code Generator', 'debug': 'Regex Debugger',
            'converter': 'Regex Converter', 'export': 'Export Matches',
            'benchmark': 'Benchmark', 'format': 'Format Regex',
        }
        self._mode_selector_guard = True
        try:
            if hasattr(self, 'function_selector') and mode in function_labels:
                self.set_control_value(self.function_selector, function_labels[mode])
            if hasattr(self, 'tools_selector'):
                self.set_control_value(self.tools_selector, tool_labels.get(mode, 'Tools...'))
        finally:
            self._mode_selector_guard = False
        panels = {
            'match': getattr(self, '_match_workspace_widget', getattr(self, '_test_editor_grid', None)),
            'substitution': getattr(self, '_substitution_panel_widget', None),
            'extraction': getattr(self, '_extraction_panel_widget', None),
            'unit_tests': getattr(self, '_unit_tests_panel_widget', None),
            'code': getattr(self, '_code_panel_widget', None),
            'debug': getattr(self, '_debug_panel_widget', None),
            'converter': getattr(self, '_converter_panel_widget', None),
            'export': getattr(self, '_export_panel_widget', None),
            'benchmark': getattr(self, '_benchmark_panel_widget', None),
            'format': getattr(self, '_format_panel_widget', None),
        }
        for name, panel in panels.items():
            if panel is not None:
                panel.setVisible(mode == name)
        label = getattr(self, '_test_title_label', None)
        if label is not None:
            label.setText({
                'match': 'TEST STRING',
                'substitution': 'SUBSTITUTION',
                'extraction': 'EXTRACTION',
                'unit_tests': 'UNIT TESTS',
                'code': 'CODE GENERATOR',
                'debug': 'REGEX DEBUGGER',
                'converter': 'REGEX CONVERTER',
                'export': 'EXPORT MATCHES',
                'benchmark': 'BENCHMARK',
                'format': 'FORMAT REGEX',
            }[mode])
        input_position = getattr(self, 'input_position', None)
        line_status = getattr(self, 'line_column_status', None)
        if input_position is not None:
            self.set_control_value(input_position, '' if mode != 'match' else self._subject_metadata())
        if line_status is not None and mode != 'match':
            self.set_control_value(line_status, '')
        if mode == 'substitution':
            self._refresh_substitution()
        elif mode == 'extraction':
            self._refresh_extraction()
        elif mode == 'unit_tests':
            self._refresh_unit_tests()
        elif mode == 'code':
            self._refresh_code_generator()
        elif mode == 'debug':
            self._refresh_debugger()
        elif mode == 'converter':
            self._refresh_converter()
        elif mode == 'export':
            self._refresh_export_matches()
        elif mode == 'format':
            self._refresh_format_regex()
        elif mode == 'benchmark':
            # Benchmark is intentionally explicit; changing text/pattern should
            # not burn CPU by rerunning hundreds of passes automatically.
            pass
        else:
            self._render_selected_match()
        return True

    def _show_match_mode(self, *_args):
        return self._set_tool_mode('match')

    def _show_substitution_mode(self, *_args):
        return self._set_tool_mode('substitution')

    def _show_extraction_mode(self, *_args):
        return self._set_tool_mode('extraction')

    def _show_unit_tests_mode(self, *_args):
        return self._set_tool_mode('unit_tests')

    def _show_code_mode(self, *_args):
        return self._set_tool_mode('code')

    def _show_debug_mode(self, *_args):
        return self._set_tool_mode('debug')

    def _show_converter_mode(self, *_args):
        return self._set_tool_mode('converter')

    def _show_export_mode(self, *_args):
        return self._set_tool_mode('export')

    def _show_benchmark_mode(self, *_args):
        return self._set_tool_mode('benchmark')

    def _show_format_mode(self, *_args):
        return self._set_tool_mode('format')

    def _replacement_changed(self, *_args):
        self._refresh_substitution()
        self._refresh_code_generator()
        return True

    def _extraction_changed(self, *_args):
        return self._refresh_extraction()

    def _converter_changed(self, *_args):
        return self._refresh_converter()

    def _export_format_changed(self, *_args):
        return self._refresh_export_matches()

    def _refresh_extraction(self):
        template_control = getattr(self, 'extraction_template_edit', None)
        result_control = getattr(self, 'extraction_result_edit', None)
        status_control = getattr(self, 'extraction_status', None)
        if template_control is None or result_control is None:
            return False
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        source = str(self.control_value(self.text_edit, '') or '')
        template = str(self.control_value(template_control, '') or '')
        if not pattern:
            self.set_control_value(result_control, '')
            if status_control is not None:
                self.set_control_value(status_control, '0 matches')
            return True
        result = _evaluate_regex_extraction(
            pattern, source, template, **self._flag_state())
        if result.get('error'):
            self.set_control_value(result_control, 'Regex / extraction error:\n{}'.format(result['error']))
            if status_control is not None:
                self.set_control_value(status_control, 'Error · {}'.format(
                    _format_regex_elapsed(result.get('elapsed_ms', 0.0))))
            return False
        self.set_control_value(result_control, result.get('output', ''))
        if status_control is not None:
            count = int(result.get('count', 0) or 0)
            self.set_control_value(
                status_control, '{} match{} · {}'.format(
                    count, '' if count == 1 else 'es',
                    _format_regex_elapsed(result.get('elapsed_ms', 0.0))))
        return True

    def _refresh_converter(self):
        output = getattr(self, 'converter_edit', None)
        if output is None:
            return False
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        result = _convert_python_regex_to_javascript(pattern, **self._flag_state())
        self.set_control_value(output, _format_regex_converter_result(result))
        return True

    def _copy_converter_result(self, *_args):
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        result = _convert_python_regex_to_javascript(pattern, **self._flag_state())
        text = '/{}/{}'.format(result.get('pattern', ''), result.get('flags', 'g'))
        copied = bool(QClipboard().setText(text))
        self.set_control_value(
            self.summary, 'Converted JavaScript regex copied.' if copied
            else 'Could not copy converted regex.')
        return copied

    def _refresh_export_matches(self):
        output = getattr(self, 'export_edit', None)
        if output is None:
            return False
        fmt = str(self.control_value(getattr(self, 'export_format', None), 'JSON') or 'JSON')
        try:
            text = _export_regex_matches(self._last_live_result or {'matches': []}, fmt)
        except ValueError as exc:
            text = str(exc)
        self.set_control_value(output, text)
        return True

    def _copy_export_matches(self, *_args):
        fmt = str(self.control_value(getattr(self, 'export_format', None), 'JSON') or 'JSON')
        try:
            text = _export_regex_matches(self._last_live_result or {'matches': []}, fmt)
        except ValueError as exc:
            self.set_control_value(self.summary, str(exc))
            return False
        copied = bool(QClipboard().setText(text))
        self.set_control_value(
            self.summary, '{} match export copied.'.format(fmt) if copied
            else 'Could not copy match export.')
        return copied

    def _refresh_format_regex(self):
        output = getattr(self, 'format_edit', None)
        if output is None:
            return False
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        self.set_control_value(output, _format_regex_structure(pattern))
        return True

    def _copy_formatted_regex(self, *_args):
        text = _format_regex_structure(self.control_value(self.pattern_edit, ''))
        copied = bool(QClipboard().setText(text))
        self.set_control_value(
            self.summary, 'Formatted regex structure copied.' if copied
            else 'Could not copy formatted regex.')
        return copied

    def _unit_tests_changed(self, *_args):
        return self._refresh_unit_tests()

    def _refresh_substitution(self):
        replacement_control = getattr(self, 'replacement_edit', None)
        result_control = getattr(self, 'substitution_result_edit', None)
        status_control = getattr(self, 'substitution_status', None)
        if replacement_control is None or result_control is None:
            return False
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        source = str(self.control_value(self.text_edit, '') or '')
        replacement = str(self.control_value(replacement_control, '') or '')
        if not pattern:
            self.set_control_value(result_control, source)
            if status_control is not None:
                self.set_control_value(status_control, '0 replacements')
            return True
        result = _evaluate_regex_substitution(
            pattern, source, replacement, **self._flag_state())
        if result.get('error'):
            self.set_control_value(result_control, 'Regex / replacement error:\n{}'.format(result['error']))
            if status_control is not None:
                self.set_control_value(status_control, 'Error · {}'.format(
                    _format_regex_elapsed(result.get('elapsed_ms', 0.0))))
            return False
        self.set_control_value(result_control, result.get('output', ''))
        count = int(result.get('count') or 0)
        if status_control is not None:
            self.set_control_value(
                status_control,
                '{} replacement{} · {}'.format(
                    count, '' if count == 1 else 's',
                    _format_regex_elapsed(result.get('elapsed_ms', 0.0))))
        return True

    def _refresh_unit_tests(self):
        input_control = getattr(self, 'unit_tests_edit', None)
        result_control = getattr(self, 'unit_tests_result_edit', None)
        status_control = getattr(self, 'unit_tests_status', None)
        if input_control is None or result_control is None:
            return False
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        source = str(self.control_value(input_control, '') or '')
        if not pattern:
            self.set_control_value(result_control, 'Enter a regular expression first.')
            if status_control is not None:
                self.set_control_value(status_control, '0 passed · 0 failed')
            return True
        result = _evaluate_regex_unit_tests(pattern, source, **self._flag_state())
        self.set_control_value(result_control, _format_regex_unit_test_results(result))
        if status_control is not None:
            if result.get('error'):
                self.set_control_value(status_control, 'Regex error')
            else:
                self.set_control_value(
                    status_control,
                    '{} passed · {} failed · {}'.format(
                        result.get('passed', 0), result.get('failed', 0),
                        _format_regex_elapsed(result.get('elapsed_ms', 0.0))))
        return not bool(result.get('error'))

    def _code_generator_changed(self, *_args):
        return self._refresh_code_generator()

    def _refresh_code_generator(self):
        code_control = getattr(self, 'code_edit', None)
        if code_control is None:
            return False
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        source = str(self.control_value(self.text_edit, '') or '')
        replacement = str(self.control_value(getattr(self, 'replacement_edit', None), '') or '')
        substitution = bool(self.control_value(
            getattr(self, 'code_use_substitution', None), False))
        code = _python_regex_code(
            pattern, source, replacement,
            substitution=substitution, **self._flag_state())
        self.set_control_value(code_control, code)
        return True

    def _copy_python_code(self, *_args):
        self._refresh_code_generator()
        code = str(self.control_value(getattr(self, 'code_edit', None), '') or '')
        if not code:
            pattern = str(self.control_value(self.pattern_edit, '') or '')
            source = str(self.control_value(self.text_edit, '') or '')
            replacement = str(self.control_value(getattr(self, 'replacement_edit', None), '') or '')
            substitution = bool(self.control_value(
                getattr(self, 'code_use_substitution', None), False))
            code = _python_regex_code(
                pattern, source, replacement,
                substitution=substitution, **self._flag_state())
        copied = bool(QClipboard().setText(code))
        self.set_control_value(
            self.summary,
            'Python code copied to clipboard.' if copied else 'Could not copy Python code.')
        return copied

    def _copy_selected_match(self, *_args):
        matches = list((getattr(self, '_last_live_result', None) or {}).get('matches') or [])
        if not matches:
            self.set_control_value(self.summary, 'No match to copy.')
            return False
        index = int(getattr(self, '_selected_match_index', 0) or 0) % len(matches)
        copied = bool(QClipboard().setText(str(matches[index].get('value') or '')))
        self.set_control_value(
            self.summary,
            'Selected match copied.' if copied else 'Could not copy selected match.')
        return copied

    def _refresh_debugger(self):
        control = getattr(self, 'debug_edit', None)
        status = getattr(self, 'debug_status', None)
        if control is None:
            return False
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        source = str(self.control_value(self.text_edit, '') or '')
        result = _regex_debug_trace(pattern, source, **self._flag_state())
        self.set_control_value(control, _format_regex_debug_trace(result))
        if status is not None:
            rows = list(result.get('rows') or [])
            match_steps = sum(1 for row in rows if row.get('state') == 'match')
            self.set_control_value(
                status,
                '{} steps · {} matching · {}'.format(
                    len(rows), match_steps,
                    _format_regex_elapsed(result.get('elapsed_ms', 0.0))))
        return True

    def _run_regex_benchmark(self, *_args):
        output = getattr(self, 'benchmark_edit', None)
        if output is None:
            return False
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        source = str(self.control_value(self.text_edit, '') or '')
        iterations_raw = self.control_value(getattr(self, 'benchmark_iterations', None), '500')
        try:
            iterations = int(str(iterations_raw or '500').strip())
        except (TypeError, ValueError):
            iterations = 500
        result = _benchmark_regex(
            pattern, source, iterations=iterations, **self._flag_state())
        self.set_control_value(output, _format_regex_benchmark(result))
        if result.get('error'):
            self.set_control_value(self.summary, 'Benchmark failed: {}'.format(result.get('error')))
            return False
        self.set_control_value(
            self.summary,
            'Benchmark complete · {} runs · average {}.'.format(
                result.get('iterations', 0),
                _format_regex_elapsed(result.get('average_ms', 0.0))))
        return True

    def _copy_regex_session(self, *_args):
        payload = _serialize_regex_session(
            self.control_value(self.pattern_edit, ''),
            self.control_value(self.text_edit, ''),
            self.control_value(getattr(self, 'replacement_edit', None), ''),
            self.control_value(getattr(self, 'unit_tests_edit', None), ''),
            extraction_template=self.control_value(
                getattr(self, 'extraction_template_edit', None), ''),
            tool_mode=getattr(self, '_tool_mode', 'match'),
            export_format=self.control_value(getattr(self, 'export_format', None), 'JSON'),
            **self._flag_state())
        copied = bool(QClipboard().setText(payload))
        self.set_control_value(
            self.summary,
            'Regex session JSON copied.' if copied else 'Could not copy regex session.')
        return copied

    def _paste_regex_session(self, *_args):
        payload = _deserialize_regex_session(QClipboard().text())
        if payload.get('error'):
            self.set_control_value(self.summary, payload.get('error'))
            return False
        self._flag_sync_guard = True
        try:
            return self._restore_regex_session(payload)
        finally:
            self._flag_sync_guard = False

    def _restore_regex_session(self, payload):
        self.set_control_value(self.pattern_edit, payload.get('pattern', ''))
        self.set_control_value(self.text_edit, payload.get('text', ''))
        replacement = getattr(self, 'replacement_edit', None)
        unit_tests = getattr(self, 'unit_tests_edit', None)
        if replacement is not None:
            self.set_control_value(replacement, payload.get('replacement', ''))
        if unit_tests is not None:
            self.set_control_value(unit_tests, payload.get('unit_tests', ''))
        extraction = getattr(self, 'extraction_template_edit', None)
        if extraction is not None:
            self.set_control_value(extraction, payload.get('extraction_template', ''))
        export_format = getattr(self, 'export_format', None)
        if export_format is not None:
            self.set_control_value(export_format, payload.get('export_format', 'JSON'))
        flag_controls = {
            'ignore_case': getattr(self, 'ignore_case', None),
            'multiline': getattr(self, 'multiline', None),
            'dotall': getattr(self, 'dotall', None),
            'verbose': getattr(self, 'verbose', None),
            'ascii_only': getattr(self, 'ascii_only', None),
        }
        for key, control in flag_controls.items():
            if control is not None:
                enabled = bool((payload.get('flags') or {}).get(key, False))
                enabled |= _regex_pattern_flag_state(payload.get('pattern', '')).get(key, False)
                self.set_control_value(control, enabled)
        pattern = str(payload.get('pattern', '') or '')
        pattern = _rewrite_regex_flags(pattern, self._flag_state())
        self.set_control_value(self.pattern_edit, pattern)
        self._flag_pattern_snapshot = pattern
        pattern_flags = getattr(self, 'pattern_flags', None)
        if pattern_flags is not None:
            self.set_control_value(pattern_flags, self._active_flag_letters())
        mode = payload.get('tool_mode', 'match')
        if mode in ('match', 'substitution', 'extraction', 'unit_tests', 'code',
                    'debug', 'converter', 'export', 'benchmark', 'format'):
            self._set_tool_mode(mode)
        self._schedule_live_test(delay=1)
        self.set_control_value(self.summary, 'Regex session imported from clipboard.')
        return True

    def _subject_metadata(self):
        text = str(self.control_value(self.text_edit, '') or '')
        lines = text.count('\n') + 1
        return '{} line{} · {} chars'.format(lines, '' if lines == 1 else 's', len(text))

    def _update_subject_status(self):
        if getattr(self, '_tool_mode', 'match') != 'match':
            return
        text = str(self.control_value(self.text_edit, '') or '')
        metadata = self._subject_metadata()
        if self.control_value(self.input_position, '') != metadata:
            self.set_control_value(self.input_position, metadata)
        hint = 'Type or paste text to test.' if not text else 'Python re · live matching'
        if self.control_value(self._subject_hint, '') != hint:
            self.set_control_value(self._subject_hint, hint)
        field = self.control_wrapper(self.text_edit)
        if hasattr(field, 'caret_position'):
            line, column = _regex_line_column(text, field.caret_position())
            label = 'Line {}, column {}'.format(line, column)
            if self.control_value(self.line_column_status, '') != label:
                self.set_control_value(self.line_column_status, label)

    def _replace_regex_editor_text(self, control, text):
        field = self.control_wrapper(control)
        if hasattr(field, 'replace_prefix'):
            field.replace_prefix(len(field.text()), text)
        else:
            self.set_control_value(control, text)

    def _load_regex_example(self, *_args):
        self._replace_regex_editor_text(self.pattern_edit, r'(?m)^(?P<kind>U|RF)(?P<axis>[1-3])$')
        self._replace_regex_editor_text(self.text_edit, 'U1\nu2\nRF3\nnoise')
        self._selected_match_index = 0
        self._input_changed()
        self.focus_control(self.text_edit)

    def _clear_regex_subject(self, *_args):
        self._replace_regex_editor_text(self.text_edit, '')
        self._input_changed()
        self.focus_control(self.text_edit)

    def _update_line_numbers(self, text):
        control = getattr(self, "line_numbers_edit", None)
        if control is not None:
            self.set_control_value(control, _regex_line_numbers(text))

    def _sync_line_number_scroll(self):
        gutter = getattr(self, "line_numbers_edit", None)
        editor = getattr(self, "text_edit", None)
        if gutter is None or editor is None:
            return False
        if getattr(self, '_native_regex_fields', None):
            source = self.control_wrapper(editor)
            target = self.control_wrapper(gutter)
            target.set_scroll_position(0, source.scroll_position()[1])
            return True
        try:
            scroll = float(dpg.get_y_scroll(editor) or 0.0)
            setter = getattr(dpg, "set_y_scroll", None)
            if callable(setter):
                setter(gutter, scroll)
                return True
        except Exception:
            pass
        return False

    def _set_inspector_visible(self, controls, toggle_button, visible):
        for control in controls:
            if control is None:
                continue
            try:
                dpg.configure_item(control, show=bool(visible))
            except Exception:
                pass
        if toggle_button is not None:
            try:
                dpg.configure_item(toggle_button, label="-" if visible else "+")
            except Exception:
                pass
        return bool(visible)

    def _toggle_explanation(self, *_args):
        control = getattr(self, "explanation_edit", None)
        try:
            visible = not bool(dpg.is_item_shown(control))
        except Exception:
            visible = True
        return self._set_inspector_visible(
            [control], getattr(self, "explanation_toggle", None), visible)

    def _toggle_match_information(self, *_args):
        control = getattr(self, "results_edit", None)
        try:
            visible = not bool(dpg.is_item_shown(control))
        except Exception:
            visible = True
        return self._set_inspector_visible(
            [control], getattr(self, "match_toggle", None), visible)

    def _toggle_quick_reference(self, *_args):
        controls = [getattr(self, "quick_reference_search", None),
                    getattr(self, "quick_reference_edit", None)]
        try:
            visible = not bool(dpg.is_item_shown(controls[-1]))
        except Exception:
            visible = True
        return self._set_inspector_visible(
            controls, getattr(self, "quick_reference_toggle", None), visible)

    def _update_match_overlay(self, text=None):
        overlay = getattr(self, "_match_overlay", None)
        if overlay is None:
            return False
        if getattr(self, '_tool_mode', 'match') != 'match':
            overlay.clear()
            self._cancel_after('_overlay_after')
            return False
        result = self._last_live_result or {"matches": []}
        matches = list(result.get("matches") or [])
        if text is None:
            text = str(self.control_value(self.text_edit, "") or "")
        if not matches:
            overlay.clear()
            self._cancel_after("_overlay_after")
            return False
        selected = max(0, min(len(matches) - 1, int(self._selected_match_index or 0)))
        groups = []
        for group in matches[selected].get("groups") or []:
            gstart, gend = group.get("span", (-1, -1))
            if gstart >= 0 and gend >= gstart:
                groups.append((gstart, gend, group.get("index", 1)))
        overlay.set_matches(
            text, [match.get("span", (0, 0)) for match in matches], groups,
            selected_index=selected)
        if overlay.ranges:
            self._schedule_overlay_sync()
        else:
            self._cancel_after("_overlay_after")
        return True

    def _set_match_navigation_enabled(self, match_count):
        enabled = int(match_count or 0) > 1
        for control in (getattr(self, 'match_prev_button', None),
                        getattr(self, 'match_next_button', None)):
            if control is None:
                continue
            try:
                dpg.configure_item(control, enabled=enabled)
            except Exception:
                pass
        for control in (getattr(self, 'match_jump_edit', None),
                        getattr(self, 'match_jump_button', None),
                        getattr(self, 'copy_match_button', None)):
            if control is not None:
                dpg.configure_item(control, enabled=int(match_count or 0) > 0)

    def _match_view_changed(self, _sender=None, value=None, _user_data=None):
        view = str(value or self.control_value(self.match_view_selector, 'All matches'))
        if view not in ('All matches', 'Selected only'):
            return False
        self._match_information_view = view
        if (self._last_live_result or {}).get('error'):
            return False  # Changing presentation must not erase compile errors.
        rendered = self._render_selected_match()
        self._reveal_selected_match()
        return rendered

    def _jump_to_match(self, *_args):
        matches = (self._last_live_result or {}).get('matches') or []
        if not matches:
            self.set_control_value(self.summary, 'No match to navigate to.')
            return False
        value = str(self.control_value(self.match_jump_edit, '') or '').strip()
        # Bound conversion as well as navigation; live results are capped at 500.
        if (not re.fullmatch(r'[0-9]+', value) or len(value) > 9
                or not 1 <= int(value) <= len(matches)):
            self.set_control_value(self.summary, 'Enter a match number from 1 to {}.'.format(len(matches)))
            return False
        self._selected_match_index = int(value) - 1
        rendered = self._render_selected_match()
        self._reveal_selected_match()
        self.set_control_value(self.summary, 'Selected match {} of {}.'.format(int(value), len(matches)))
        return rendered

    def _render_selected_match(self):
        result = self._last_live_result or {"matches": []}
        matches = list(result.get('matches') or [])
        if not matches:
            self._selected_match_index = 0
            match_position = getattr(self, 'match_position', None)
            if match_position is not None:
                self.set_control_value(match_position, '0 / 0')
            self.set_control_value(self.results_edit, 'No matches.')
            line_status = getattr(self, 'line_column_status', None)
            if line_status is not None:
                self.set_control_value(line_status, 'Line 1, column 1')
            self._set_match_navigation_enabled(0)
            overlay = getattr(self, '_match_overlay', None)
            if overlay is not None:
                overlay.clear()
            self._refresh_inline_colors()
            return False
        self._selected_match_index = int(getattr(self, '_selected_match_index', 0) or 0) % len(matches)
        match_position = getattr(self, 'match_position', None)
        if match_position is not None:
            self.set_control_value(
                match_position, '{} / {}'.format(self._selected_match_index + 1, len(matches)))
        selected_match = matches[self._selected_match_index]
        if getattr(self, '_match_information_view', 'All matches') == 'Selected only':
            information = _format_regex_selected_match(result, self._selected_match_index)
        else:
            information = 'MATCH {} OF {} · selected\n\n{}'.format(
                self._selected_match_index + 1, len(matches), _format_regex_match_information(result))
        self.set_control_value(self.results_edit, information)
        line_col = selected_match.get("line_column") or (1, 1)
        line_status = getattr(self, "line_column_status", None)
        if line_status is not None:
            self.set_control_value(
                line_status, "Line {}, column {}".format(line_col[0], line_col[1]))
        self._set_match_navigation_enabled(len(matches))
        self._update_match_overlay()
        self._refresh_inline_colors()
        return True

    def _previous_match(self, *_args):
        matches = list((self._last_live_result or {}).get('matches') or [])
        if not matches:
            return False
        self._selected_match_index = (int(getattr(self, '_selected_match_index', 0) or 0) - 1) % len(matches)
        rendered = self._render_selected_match()
        self._reveal_selected_match()
        return rendered

    def _next_match(self, *_args):
        matches = list((self._last_live_result or {}).get('matches') or [])
        if not matches:
            return False
        self._selected_match_index = (int(getattr(self, '_selected_match_index', 0) or 0) + 1) % len(matches)
        rendered = self._render_selected_match()
        self._reveal_selected_match()
        return rendered

    def _reveal_selected_match(self):
        # Only explicit navigation scrolls; live recoloring never jumps away
        # from the location being edited. Plain-text fallback stays unchanged.
        if (not getattr(self, '_native_regex_fields', None)
                or getattr(self, '_tool_mode', 'match') != 'match'):
            return False
        matches = (self._last_live_result or {}).get('matches') or []
        index = self._selected_match_index
        if not 0 <= index < len(matches):
            return False
        start, end = matches[index]['span']
        subject = self.control_wrapper(self.text_edit)
        text = subject.text()
        if not 0 <= start <= end <= len(text) or text[start:end] != matches[index]['value']:
            return False  # A native edit may still be waiting for live evaluation.
        subject.reveal_position(start)
        info = self.control_wrapper(self.results_edit)
        marker = '\nMATCH {}\n'.format(index + 1)
        position = info.text().find(marker)
        if position >= 0:
            info.reveal_position(position + 1)
        elif getattr(self, '_match_information_view', 'All matches') == 'Selected only':
            info.reveal_position(0)
        self._sync_line_number_scroll()
        return True

    def _input_changed(self, *_args):
        if getattr(self, '_flag_sync_guard', False):
            return
        self._sync_flags_from_pattern()
        self._refresh_inline_pattern()
        self._schedule_live_test()

    def _refresh_inline_pattern(self, error_position=None):
        self._regex_error_position = error_position
        self._refresh_inline_colors()

    def _flag_changed(self, *_args):
        if getattr(self, '_flag_sync_guard', False):
            return
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        updated = _rewrite_regex_flags(pattern, self._flag_state())
        self._flag_sync_guard = True
        try:
            if updated != pattern:
                field = self.control_wrapper(self.pattern_edit)
                if hasattr(field, 'replace_prefix'):
                    end, _ = _regex_global_prefix(pattern)
                    new_end = len(updated) - len(pattern) + end
                    field.replace_prefix(end, updated[:new_end])
                else:
                    self.set_control_value(self.pattern_edit, updated)
            self._flag_pattern_snapshot = updated
        finally:
            self._flag_sync_guard = False
        self._refresh_inline_pattern()
        pattern_flags = getattr(self, "pattern_flags", None)
        if pattern_flags is not None:
            self.set_control_value(pattern_flags, self._active_flag_letters())
        self._schedule_live_test()
        self._refresh_substitution()
        self._refresh_extraction()
        self._refresh_unit_tests()
        self._refresh_code_generator()

        self._refresh_debugger()
        self._refresh_converter()
        self._refresh_export_matches()
        self._refresh_format_regex()

    def _sync_flags_from_pattern(self):
        if getattr(self, '_flag_sync_guard', False):
            return
        pattern = str(self.control_value(self.pattern_edit, '') or '')
        if pattern == getattr(self, '_flag_pattern_snapshot', None):
            return
        self._flag_sync_guard = True
        try:
            for key, enabled in _regex_pattern_flag_state(pattern).items():
                control = getattr(self, key, None)
                if control is not None:
                    self.set_control_value(control, enabled)
            self._flag_pattern_snapshot = pattern
            control = getattr(self, 'pattern_flags', None)
            if control is not None:
                self.set_control_value(control, self._active_flag_letters())
        finally:
            self._flag_sync_guard = False

    def _quick_reference_changed(self, *_args):
        if self._finished:
            return
        query = str(self.control_value(self.quick_reference_search, "") or "")
        self.set_control_value(self.quick_reference_edit, _format_regex_quick_reference(query))

    def _cancel_after(self, attribute):
        token = getattr(self, attribute, None)
        setattr(self, attribute, None)
        if token is None:
            return
        cancel = getattr(self.view, "after_cancel", None)
        if callable(cancel):
            try:
                cancel(token)
            except Exception:
                pass

    def _schedule_live_test(self, *_args, **kwargs):
        if self._finished:
            return None
        delay = int(kwargs.get("delay", self.LIVE_DEBOUNCE_MS))
        self._cancel_after("_live_after")
        try:
            self._live_after = self.view.after(delay, self._run_live_regex)
        except Exception:
            self._live_after = None
            self._run_live_regex()
        return self._live_after

    def _schedule_overlay_sync(self):
        if self._finished or self._overlay_after is not None:
            return self._overlay_after
        overlay = self._match_overlay
        if overlay is None or not overlay.ranges:
            return None
        try:
            self._overlay_after = self.view.after(
                self.OVERLAY_SYNC_MS, self._sync_match_overlay)
        except Exception:
            self._overlay_after = None
        return self._overlay_after

    def _sync_match_overlay(self):
        self._overlay_after = None
        if self._finished:
            return
        overlay = self._match_overlay
        if overlay is not None:
            overlay.refresh()
        self._sync_line_number_scroll()
        self._schedule_overlay_sync()

    def _run_live_regex(self, *_args):
        self._live_after = None
        if self._finished:
            return False
        self._sync_flags_from_pattern()
        pattern = str(self.control_value(self.pattern_edit, "") or "")
        text = str(self.control_value(self.text_edit, "") or "")
        self._update_line_numbers(text)
        flags = self._flag_state()
        flag_letters = _regex_flag_letters(**flags)
        pattern_flags = getattr(self, "pattern_flags", None)
        if pattern_flags is not None:
            self.set_control_value(pattern_flags, flag_letters)
        explanation = _format_regex_explanation(pattern)
        if pattern:
            explanation = pattern + "\n\n" + explanation + "\n\n" + _format_regex_flag_explanation(flag_letters)
        self.set_control_value(self.explanation_edit, explanation)
        if not pattern:
            self._refresh_inline_pattern()
            if self._match_overlay is not None:
                self._match_overlay.clear()
            self._cancel_after("_overlay_after")
            self._last_live_result = {"matches": []}
            self._selected_match_index = 0
            self._render_selected_match()
            self.set_control_value(self.pattern_status, "0 matches · 0 tokens · 0 groups · ~0.000 ms")
            self.set_control_value(self.summary, "Enter a regular expression to start live matching.")
            self._refresh_substitution()
            self._refresh_extraction()
            self._refresh_unit_tests()
            self._refresh_code_generator()
            self._refresh_debugger()
            self._refresh_converter()
            self._refresh_export_matches()
            self._refresh_format_regex()
            return True

        result = self.evaluate(pattern, text, **flags)
        self._refresh_inline_pattern(error_position=result.get('error_position'))
        error = result.get("error") or ""
        elapsed_ms = float(result.get("elapsed_ms") or 0.0)
        if error:
            if self._match_overlay is not None:
                self._match_overlay.clear()
            self._cancel_after("_overlay_after")
            token_count = len(_regex_token_explanations(pattern))
            self.set_control_value(self.pattern_status, _format_regex_live_header(
                0, token_count, elapsed_ms, error=error))
            self._last_live_result = result
            self._selected_match_index = 0
            match_position = getattr(self, 'match_position', None)
            if match_position is not None:
                self.set_control_value(match_position, '0 / 0')
            self._set_match_navigation_enabled(0)
            error_line = result.get("error_line")
            error_column = result.get("error_column")
            location = (" · line {}, column {}".format(error_line, error_column)
                        if error_line is not None and error_column is not None else "")
            self.set_control_value(
                self.summary, "Regex error{} · {} · {}".format(
                    location, _format_regex_elapsed(elapsed_ms), error))
            pointer = ""
            error_pos = result.get("error_position")
            if error_pos is not None:
                pointer = "\nPosition {}{}".format(error_pos, location)
            self.set_control_value(
                self.results_edit, "Regex error:\n{}{}".format(error, pointer))
            self._refresh_substitution()
            self._refresh_extraction()
            self._refresh_unit_tests()
            self._refresh_code_generator()
            self._refresh_debugger()
            self._refresh_converter()
            self._refresh_export_matches()
            self._refresh_format_regex()
            self._refresh_inline_colors()
            return False

        matches = result.get("matches") or []
        self._last_live_result = result
        if matches:
            self._selected_match_index = min(int(getattr(self, '_selected_match_index', 0) or 0), len(matches) - 1)
        else:
            self._selected_match_index = 0
        self._render_selected_match()
        token_count = len(_regex_token_explanations(pattern))
        named_count = len(result.get("named_groups") or {})
        top_status = _format_regex_live_header(
            len(matches), token_count, elapsed_ms,
            group_count=result.get("group_count", 0),
            named_count=named_count,
            truncated=bool(result.get("truncated")),
        )
        self.set_control_value(self.pattern_status, top_status)
        match_label = "{}+".format(len(matches)) if result.get("truncated") else str(len(matches))
        summary = "{} match{} · {} token{} · {} capture group{}".format(
            match_label, "" if match_label == "1" else "es",
            token_count, "" if token_count == 1 else "s",
            result.get("group_count", 0),
            "" if result.get("group_count", 0) == 1 else "s")
        if named_count:
            summary += " · {} named".format(named_count)
        summary += " · {} · Python re · live".format(_format_regex_elapsed(elapsed_ms))
        self.set_control_value(self.summary, summary)
        self._refresh_substitution()
        self._refresh_extraction()
        self._refresh_unit_tests()
        self._refresh_code_generator()
        self._refresh_debugger()
        self._refresh_converter()
        self._refresh_export_matches()
        self._refresh_format_regex()
        return True

    # Compatibility for older call sites/tests; matching is now live.
    def _test_regex(self, *_args):
        self._cancel_after("_live_after")
        return self._run_live_regex()

    def destroy(self):
        if self._finished:
            return
        self._finished = True
        self._cancel_after("_live_after")
        self._cancel_after("_overlay_after")
        self._cancel_after('_native_after')
        overlay, self._match_overlay = self._match_overlay, None
        if overlay is not None:
            overlay.delete()
        return super().destroy()


__all__ = [
    'REGEX_QUICK_REFERENCE',
    'REGEX_QUICK_REFERENCE_GROUPS',
    '_REGEX_ESCAPE_HELP',
    '_ordinal',
    '_format_regex_elapsed',
    '_format_regex_live_header',
    '_regex_flag_letters',
    '_REGEX_FLAG_KEYS',
    '_regex_global_prefix',
    '_regex_pattern_flag_state',
    '_rewrite_regex_flags',
    '_regex_line_numbers',
    '_regex_zero_width_fragment',
    '_normalize_regex_replacement',
    '_regex_flags_value',
    '_evaluate_regex_substitution',
    '_evaluate_regex_extraction',
    '_regex_match_export_rows',
    '_export_regex_matches',
    '_convert_python_regex_to_javascript',
    '_format_regex_converter_result',
    '_format_regex_structure',
    '_regex_error_location',
    '_parse_regex_unit_tests',
    '_evaluate_regex_unit_tests',
    '_format_regex_unit_test_results',
    '_regex_debug_trace',
    '_format_regex_debug_trace',
    '_benchmark_regex',
    '_format_regex_benchmark',
    '_serialize_regex_session',
    '_deserialize_regex_session',
    '_python_regex_code',
    '_regex_token_explanations',
    '_format_regex_explanation',
    '_format_regex_flag_explanation',
    '_format_regex_quick_reference',
    '_regex_line_column',
    '_format_regex_selected_match',
    '_format_regex_match_information',
    '_first_regex_pattern',
    '_regex_test_text',
    '_regex_highlight_fragments',
    '_RegexMatchOverlay',
    'RegexTesterDialog',
]
