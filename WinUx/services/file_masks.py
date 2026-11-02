"""Compiled WinSCP-style masks for listing metadata, never filesystem probes.

This is a display-item matcher, not a recursive transfer traversal policy.
Operation-relative paths (./), calendar-year/rounded relative times and mask
builders are deliberately not implemented yet and raise clear validation errors.
"""
from datetime import datetime
from fnmatch import translate
from functools import lru_cache
import math
import re
import time

MAX_MASK_LENGTH = 4096


class _PathPattern:
    """Match components without letting a filename '*' swallow subfolders.

    A leading */ is a partial-path prefix and may span any number of parents.
    Other components are matched separately, including Windows drive letters.
    """
    def __init__(self, glob):
        components = glob.split('/')
        self.partial = components[0] == '*'
        if self.partial:
            components = components[1:]
        self.parts = tuple(re.compile(translate(part)) for part in components)

    def fullmatch(self, path):
        parts = path.split('/')
        if self.partial:
            if len(parts) < len(self.parts):
                return False
            parts = parts[-len(self.parts):]
        elif len(parts) != len(self.parts):
            return False
        return all(pattern.fullmatch(part) for pattern, part in zip(self.parts, parts))


def _class_end(text, start):
    end = start + 1
    if end < len(text) and text[end] in '!^':
        end += 1
    if end < len(text) and text[end] == ']':
        end += 1
    end = text.find(']', end)
    return end + 1 if end >= 0 else 0


def _split(expression):
    """Preserve doubled literals until pattern/constraint parsing is done."""
    parts, excluded, buffer, has_pipe, index = [], [], [], False, 0
    target = parts
    while index < len(expression):
        char = expression[index]
        if char == '[':
            end = _class_end(expression, index)
            if end:
                buffer.append(expression[index:end])
                index = end
                continue
        if char in ';,|':
            if index + 1 < len(expression) and expression[index + 1] == char:
                buffer.append(char + char)
                index += 2
                continue
            if ''.join(buffer).strip():
                target.append(''.join(buffer).strip())
            buffer = []
            if char == '|':
                if has_pipe:
                    raise ValueError('Use one exclusion separator (|); escape a literal pipe as ||.')
                has_pipe = True
                target = excluded
        else:
            buffer.append(char)
        index += 1
    if ''.join(buffer).strip():
        target.append(''.join(buffer).strip())
    return parts, excluded


def _constraint_value(text):
    if re.fullmatch(r'\d+(?:\.\d+)?[KMG]?', text, re.I):
        suffix = text[-1].upper()
        factor = {'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3}.get(suffix, 1)
        number = float(text[:-1] if suffix in 'KMG' else text) * factor
        if not math.isfinite(number):
            raise ValueError('Size constraint is too large.')
        return 'size', number
    relative = re.fullmatch(r'(\d+)([DHNS])', text, re.I)
    if relative:
        seconds = float(relative[1]) * {'D': 86400, 'H': 3600, 'N': 60, 'S': 1}[relative[2].upper()]
        if not math.isfinite(seconds):
            raise ValueError('Relative time constraint is too large.')
        return 'relative', seconds
    if text.casefold() in ('today', 'yesterday'):
        return text.casefold(), 0
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?', text):
        try:
            return 'mtime', datetime.fromisoformat(text).timestamp()
        except (ValueError, OSError, OverflowError):
            pass
    raise ValueError('Invalid mask constraint: {}. Use bytes/K/M/G, YYYY-MM-DD [HH:MM[:SS]], '
                     'an interval such as 30D or 2H, today or yesterday.'.format(text))


def _pattern(raw):
    pattern, constraints, index = [], [], 0
    while index < len(raw):
        char = raw[index]
        if char == '[':
            end = _class_end(raw, index)
            if end:
                pattern.append(raw[index:end])
                index = end
                continue
        if char in '<>':
            if index + 1 < len(raw) and raw[index + 1] == char:
                pattern.append(char)
                index += 2
                continue
            break
        if char in ';,|' and index + 1 < len(raw) and raw[index + 1] == char:
            pattern.append(char)
            index += 2
            continue
        pattern.append(char)
        index += 1
    while index < len(raw):
        operator = raw[index]
        if operator not in '<>':
            raise ValueError('Invalid mask constraint operator.')
        index += 1
        if index < len(raw) and raw[index] == '=':
            operator += '='
            index += 1
        start = index
        while index < len(raw) and raw[index] not in '<>':
            index += 1
        kind, value = _constraint_value(raw[start:index].strip())
        constraints.append((operator, kind, value))
    glob = ''.join(pattern).strip().replace('\\', '/').casefold() or '*'
    if glob.startswith('./') or '..' in glob.split('/'):
        raise ValueError('Operation-relative paths (./ or ../) are not supported in display masks yet.')
    directory = glob.endswith('/')
    glob = glob.rstrip('/') if directory and glob != '/' else glob
    path = '/' in glob or bool(re.match(r'^[a-z]:', glob))
    # WinSCP's documented DOS-style exceptions apply to the filename component.
    prefix, separator, basename = glob.rpartition('/')
    no_extension = basename == '*.'
    if basename in ('*.*', '*.'):
        glob = prefix + separator + '*'
    return (_PathPattern(glob) if path else re.compile(translate(glob)),
            path, directory, no_extension, tuple(constraints))


def _compare(actual, operator, expected):
    if operator == '>':
        return actual > expected
    if operator == '>=':
        return actual >= expected
    if operator == '<':
        return actual < expected
    return actual <= expected


class FileMask:
    def __init__(self, expression):
        if not isinstance(expression, str) or len(expression) > MAX_MASK_LENGTH:
            raise ValueError('File mask must contain at most {} characters.'.format(MAX_MASK_LENGTH))
        if any(char in expression for char in '\x00\n\r'):
            raise ValueError('File masks cannot contain NUL or newline characters.')
        includes, excludes = _split(expression)
        self.includes = tuple(_pattern(raw) for raw in includes)
        self.excludes = tuple(_pattern(raw) for raw in excludes)
        entries = self.includes + self.excludes
        self._simple_names = all(not any(entry[1:]) for entry in entries)
        self._name_includes = tuple(entry[0].fullmatch for entry in self.includes) if self._simple_names else ()
        self._name_excludes = tuple(entry[0].fullmatch for entry in self.excludes) if self._simple_names else ()
        self.time_dependent = any(kind in ('relative', 'today', 'yesterday')
                                  for entry in self.includes + self.excludes
                                  for _, kind, _ in entry[-1])

    @staticmethod
    def _matches(entry, item, now):
        regex, path_mask, directory, no_extension, constraints = entry
        if directory and not item.is_dir:
            return False
        name = getattr(item, 'cached_name_sort', None)
        if name is None:
            name = str(item.name).casefold()
        if no_extension and '.' in name:
            return False
        target = (str(getattr(item, 'path', '') or '').replace('\\', '/').rstrip('/').casefold()
                  if path_mask else name)
        if not regex.fullmatch(target):
            return False
        for operator, kind, value in constraints:
            if kind == 'size':
                actual = 0 if item.is_dir else getattr(item, 'size', None)
                expected = value
            else:
                actual = getattr(item, 'mtime', getattr(item, 'modified', None))
                expected = value
                if kind == 'relative':
                    if item.is_dir:
                        return False
                    expected = now - value
                elif kind in ('today', 'yesterday'):
                    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
                    if kind == 'yesterday':
                        from datetime import timedelta
                        today -= timedelta(days=1)
                    expected = today.timestamp()
            if actual is None:
                return False
            try:
                actual = float(actual)
                if not math.isfinite(actual) or not _compare(actual, operator, expected):
                    return False
            except (TypeError, ValueError, OverflowError):
                return False
        return True

    def __call__(self, item, *, now=None):
        # Preserve the cheap common case for large listings. Path/metadata
        # interpretation is needed only by rules that actually request it.
        if self._simple_names:
            name = getattr(item, 'cached_name_sort', None)
            if name is None:
                name = str(item.name).casefold()
            return ((not self._name_includes or any(match(name) for match in self._name_includes)) and
                    not any(match(name) for match in self._name_excludes))
        # Read the clock only for relative masks, not for every ordinary row.
        if now is None and self.time_dependent:
            now = time.time()
        return ((not self.includes or any(self._matches(entry, item, now) for entry in self.includes)) and
                not any(self._matches(entry, item, now) for entry in self.excludes))


@lru_cache(maxsize=256)
def compile_file_mask(expression):
    return FileMask(expression)
