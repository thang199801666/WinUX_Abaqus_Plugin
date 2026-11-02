"""Non-executing Python-regex lexer for the workbench's colored preview.

This is presentation only. Python re remains authoritative for syntax and spans.
Incomplete input still produces contiguous tokens without compiling the pattern.
"""
import re


REGEX_GROUP_COLORS = ((0, 120, 180, 255), (166, 56, 139, 255),
                      (24, 132, 66, 255), (190, 87, 0, 255), (103, 66, 173, 255))
REGEX_SYNTAX_COLORS = {
    'literal': (43, 48, 55, 255), 'class': (0, 112, 177, 255),
    'escape': (0, 121, 119, 255), 'quantifier': (133, 52, 164, 255),
    'anchor': (180, 53, 73, 255), 'alternation': (183, 91, 0, 255),
    'group': (103, 66, 173, 255), 'comment': (109, 119, 126, 255),
    'error': (201, 40, 53, 255),
}

REGEX_GROUP_BACKGROUNDS = ((218, 234, 174), (193, 216, 248), (244, 218, 180),
                           (239, 204, 224), (220, 208, 244))


def regex_pattern_spans(pattern, *, verbose=False, error_position=None, limit=3000):
    """Inline foreground/background formats; never changes the pattern text."""
    tokens = regex_syntax_tokens(pattern, verbose=verbose, error_position=error_position)
    regions, starts = [], {}
    for token in tokens:
        group = token['group']
        if group and token['description'].startswith(('Capture group', 'Named capture group')):
            starts[group] = token['start']
        elif group and token['description'] == 'End group' and group in starts:
            regions.append((starts.pop(group), token['end'], group))
    regions.extend((start, len(pattern), group) for group, start in starts.items())
    spans = []
    for token in tokens[:limit]:
        enclosing = [(a, b, group) for a, b, group in regions
                     if a <= token['start'] < b]
        group = min(enclosing, key=lambda region: region[1] - region[0])[2] if enclosing else None
        background = REGEX_GROUP_BACKGROUNDS[(group - 1) % len(REGEX_GROUP_BACKGROUNDS)] if group else (255, 255, 255)
        if token['kind'] == 'error':
            background = (255, 215, 220)
        spans.append((token['start'], token['end'], token['color'][:3], background))
    return spans


def regex_subject_spans(result, selected_index=0, *, limit=3000):
    spans = []
    foreground = (35, 40, 46)
    for index, match in enumerate(result.get('matches') or []):
        start, end = match['span']
        if end > start:
            spans.append((start, end, foreground, (184, 221, 245) if index == selected_index else (219, 239, 251)))
        for group in match.get('groups') or []:
            start, end = group.get('span', (-1, -1))
            if 0 <= start < end:
                number = max(1, group.get('index', 1))
                background = REGEX_GROUP_BACKGROUNDS[(number - 1) % len(REGEX_GROUP_BACKGROUNDS)]
                spans.append((start, end, foreground, background))
            if len(spans) >= limit:
                return spans[:limit]
        if len(spans) >= limit:
            return spans[:limit]
    return spans


def regex_inspector_spans(text, named_groups=None):
    """Share group colors with the selected-match inspector's labels/values."""
    spans, offset = [], 0
    for line in text.splitlines(keepends=True):
        match = re.search(r'\bGroup (\d+)\b', line)
        group = int(match.group(1)) if match else None
        named = re.search(r'Named <([^>]+)>', line)
        if named:
            group = (named_groups or {}).get(named.group(1))
        if group:
            spans.append((offset, offset + len(line.rstrip('\n')),
                (35, 40, 46), REGEX_GROUP_BACKGROUNDS[(group - 1) % len(REGEX_GROUP_BACKGROUNDS)]))
        elif 'Full match' in line:
            spans.append((offset, offset + len(line.rstrip('\n')), (35, 40, 46), (219, 239, 251)))
        offset += len(line)
    return spans


def regex_explanation_spans(pattern, explanation, *, verbose=False, error_position=None):
    spans = regex_pattern_spans(pattern, verbose=verbose, error_position=error_position)
    offset = 0
    styles = {start: (foreground, background) for start, end, foreground, background in spans}
    for line in explanation.splitlines(keepends=True):
        label = re.search(r'\[(\d+):(\d+)\]', line)
        if label:
            start, end = map(int, label.groups())
            quoted = repr(pattern[start:end])
            column = line.find(quoted, label.end())
            if column >= 0 and start in styles:
                foreground, background = styles[start]
                spans.append((offset + column, offset + column + len(quoted), foreground, background))
        offset += len(line)
    return spans


def regex_syntax_tokens(pattern, *, verbose=False, error_position=None):
    source = str(pattern or '')
    tokens, stack, names = [], [], {}
    group_count = 0
    i = 0

    def emit(start, end, kind, description, group=None):
        color = (REGEX_GROUP_COLORS[(group - 1) % len(REGEX_GROUP_COLORS)]
                 if group else REGEX_SYNTAX_COLORS[kind])
        # Split a token around the compile error so only its actual position is
        # marked. Offsets remain Python character offsets, including Unicode.
        cuts = [start, end]
        if error_position is not None and start <= error_position < end:
            cuts = sorted(set(cuts + [error_position, error_position + 1]))
        for left, right in zip(cuts, cuts[1:]):
            invalid = error_position is not None and left == error_position
            tokens.append(dict(start=left, end=right, text=source[left:right],
                kind='error' if invalid else kind, group=group,
                color=REGEX_SYNTAX_COLORS['error'] if invalid else color,
                description=description))

    while i < len(source):
        start, ch = i, source[i]
        if verbose and (ch.isspace() or ch == '#'):
            if ch == '#':
                end = source.find('\n', i)
                i = len(source) if end < 0 else end
            else:
                while i < len(source) and source[i].isspace():
                    i += 1
            emit(start, i, 'comment', 'Ignored in verbose mode')
        elif ch == '\\':
            i = min(len(source), i + 2)
            code = source[start + 1:i]
            if code in ('x', 'u', 'U'):
                i = min(len(source), i + {'x': 2, 'u': 4, 'U': 8}[code])
            elif code == 'N' and source[i:i + 1] == '{':
                end = source.find('}', i)
                i = len(source) if end < 0 else end + 1
            elif code and code.isdigit():
                while i < len(source) and i - start < 4 and source[i].isdigit():
                    i += 1
            kind = 'class' if code in ('d', 'D', 'w', 'W', 's', 'S') else 'escape'
            if code in ('A', 'Z', 'b', 'B'):
                kind = 'anchor'
            emit(start, i, kind, 'Escape / character class / assertion')
        elif ch == '[':
            i += 1
            if source[i:i + 1] == '^':
                i += 1
            # ']' immediately after '[' or '[^' is a literal member.
            if source[i:i + 1] == ']':
                i += 1
            while i < len(source):
                if source[i] == '\\':
                    i = min(len(source), i + 2)
                elif source[i] == ']':
                    i += 1
                    break
                else:
                    i += 1
            emit(start, i, 'class', 'Character set (including escapes and ranges)')
        elif source.startswith('(?#', i):
            end = source.find(')', i + 3)
            i = len(source) if end < 0 else end + 1
            emit(start, i, 'comment', 'Regex comment')
        elif source.startswith('(?P=', i):
            end = source.find(')', i + 4)
            i = len(source) if end < 0 else end + 1
            name = source[start + 4:i - 1] if end >= 0 else ''
            emit(start, i, 'group', 'Named backreference', names.get(name))
        elif ch == '(':
            i += 1
            group = None
            was_verbose = verbose
            desc = 'Non-capturing group / assertion'
            if source.startswith('(?P<', start):
                end = source.find('>', start + 4)
                i = len(source) if end < 0 else end + 1
                group_count += 1
                group = group_count
                if end >= 0:
                    names[source[start + 4:end]] = group
                desc = 'Named capture group {}'.format(group)
            elif source[start + 1:start + 2] != '?':
                group_count += 1
                group = group_count
                desc = 'Capture group {}'.format(group)
            else:
                flag = re.match(r'\(\?([aiLmsux]*)(?:-([imsx]+))?([:)])', source[start:])
                if flag:
                    i = start + flag.end()
                    if 'x' in flag.group(1):
                        verbose = True
                    if 'x' in (flag.group(2) or ''):
                        verbose = False
                    if flag.group(3) == ')':
                        emit(start, i, 'group', 'Inline flags')
                        continue
                    desc = 'Scoped flags'
                else:
                    for prefix in ('(?<=', '(?<!', '(?:', '(?=', '(?!', '(?>'):
                        if source.startswith(prefix, start):
                            i = start + len(prefix)
                            break
            stack.append((group, was_verbose))
            emit(start, i, 'group', desc, group)
        elif ch == ')':
            i += 1
            group, verbose = stack.pop() if stack else (None, verbose)
            emit(start, i, 'group', 'End group', group)
        elif ch in '*+?' or ch == '{' and re.match(r'\{(?:\d+(?:,\d*)?|,\d+)\}', source[i:]):
            if ch == '{':
                i += re.match(r'\{(?:\d+(?:,\d*)?|,\d+)\}', source[i:]).end()
            else:
                i += 1
            if source[i:i + 1] in ('?', '+'):
                i += 1
            emit(start, i, 'quantifier', 'Repetition (optional lazy/possessive suffix)')
        elif ch in '.^$|':
            i += 1
            kind = 'class' if ch == '.' else 'alternation' if ch == '|' else 'anchor'
            emit(start, i, kind, {'.': 'Any character', '^': 'Start anchor',
                                 '$': 'End anchor', '|': 'Alternative'}[ch])
        else:
            i += 1
            while i < len(source) and source[i] not in '\\[()*+?{.^$|' and not (
                    verbose and (source[i].isspace() or source[i] == '#')):
                i += 1
            emit(start, i, 'literal', 'Literal text')
    return tokens
