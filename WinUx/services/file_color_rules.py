"""Ordered filename-color rules; no GUI, filesystem or SSH work on matching."""
import re
import stat
from .file_masks import compile_file_mask

FILE_COLORS = {
    'hidden': (112, 112, 112, 255), 'symlink': (0, 105, 120, 255),
    'directory': (0, 70, 165, 255), 'executable': (24, 112, 48, 255),
    'archive': (150, 55, 30, 255), 'image': (112, 60, 145, 255),
}
SCOPES = {'any': 'All items', 'file': 'Files', 'directory': 'Folders',
          'hidden': 'Hidden items', 'symlink': 'Links', 'executable': 'Executables'}
MAX_RULES = 128


def color_hex(value):
    if isinstance(value, str):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', value.strip()):
            raise ValueError('Color must use #RRGGBB, for example #0046A5.')
        return value.strip().upper()
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 4):
        raise ValueError('Color must contain three RGB channels.')
    if any(type(channel) is not int or not 0 <= channel <= 255 for channel in value):
        raise ValueError('RGB channels must be integers from 0 to 255.')
    return '#{:02X}{:02X}{:02X}'.format(*value[:3])


def default_color_rules():
    masks = {
        'hidden': '*', 'symlink': '*', 'directory': '*', 'executable': '*',
        'archive': '*.zip;*.7z;*.rar;*.tar;*.gz;*.bz2;*.xz;*.tgz;*.zst',
        'image': '*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.tif;*.tiff;*.svg;*.webp;*.ico',
    }
    names = ('Hidden items', 'Links', 'Folders', 'Executables', 'Archives', 'Images')
    return [dict(name=name, enabled=True, mask=masks[key],
                 scope=key if key in SCOPES else 'file', color=color_hex(FILE_COLORS[key]))
            for key, name in zip(FILE_COLORS, names)]


def normalize_color_rules(rules):
    """Strict validation for Save; None migrates old preferences to defaults."""
    if rules is None:
        return default_color_rules()
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError('Use a list of at most {} color rules.'.format(MAX_RULES))
    normalized = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError('Each color rule must be an object.')
        name = str(rule.get('name', '')).strip()
        mask = str(rule.get('mask', '')).strip()
        scope = rule.get('scope', 'any')
        if not name or len(name) > 96:
            raise ValueError('Rule name must contain 1-96 characters.')
        if not mask or len(mask) > 1024:
            raise ValueError('Enter a file mask containing 1-1024 characters.')
        matcher = compile_file_mask(mask)
        if not matcher.includes and not matcher.excludes:
            raise ValueError('Enter at least one filename pattern.')
        if scope not in SCOPES:
            raise ValueError('Unknown color rule scope.')
        if type(rule.get('enabled', True)) is not bool:
            raise ValueError('Rule enabled state must be true or false.')
        normalized.append(dict(name=name, enabled=rule.get('enabled', True), mask=mask,
                               scope=scope, color=color_hex(rule.get('color'))))
    return normalized


def load_color_rules(rules):
    """Malformed stored settings must never prevent browsing/startup."""
    try:
        return normalize_color_rules(rules)
    except (ValueError, TypeError):
        return default_color_rules()


def _scope_matches(scope, item):
    data, mode = item.data, item.data.get('mode')
    if scope == 'any':
        return True
    if scope == 'file':
        return not item.is_dir
    if scope == 'directory':
        return item.is_dir
    if scope == 'hidden':
        return data.get('is_hidden') or item.name.startswith('.')
    if scope == 'symlink':
        return data.get('is_symlink') or (mode is not None and stat.S_ISLNK(mode))
    return ((mode is not None and stat.S_ISREG(mode) and mode & 0o111) or
            (mode is None and item.extension.casefold() in ('.exe', '.com', '.bat', '.cmd', '.ps1')))


class FileColorRules:
    """Compile once per preference change; first enabled matching rule wins."""
    def __init__(self, rules=None):
        self.rules = normalize_color_rules(rules)
        self._compiled = tuple(
            (rule['scope'], compile_file_mask(rule['mask']),
             tuple(int(rule['color'][i:i + 2], 16) for i in (1, 3, 5)) + (255,))
            for rule in self.rules if rule['enabled'])

    def __call__(self, item):
        if item.data.get('parent'):
            return None
        for scope, matcher, color in self._compiled:
            if _scope_matches(scope, item) and matcher(item):
                return color
        return None
