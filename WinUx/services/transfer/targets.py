"""Portable, single-component destination names for explicitly renamed copies."""
import re


def validate_target_name(name):
    if (not isinstance(name, str) or not name or len(name) > 255 or name in ('.', '..')
            or name != name.strip() or name.endswith('.') or
            any(ord(char) < 32 or char in '\\/:*?"<>|' for char in name)):
        raise ValueError('Enter a single file name (no paths, trailing spaces/dots or reserved characters).')
    stem = name.split('.', 1)[0].rstrip(' .').upper()
    if stem in ('CON', 'PRN', 'AUX', 'NUL') or re.fullmatch(r'(?:COM|LPT)[1-9¹²³]', stem):
        raise ValueError('The destination name is reserved by Windows.')
    return name


def validate_target_names(sources, target_names, *, windows=False):
    """Validate a source-path -> new-basename map before any transfer writes."""
    names = dict(target_names or {})
    keys = {str(source) for source in sources}
    if set(names) - keys:
        raise ValueError('A renamed destination does not belong to this transfer.')
    fold = str.casefold if windows else lambda value: value
    originals = {fold(source.name) for source in sources}
    for key, name in names.items():
        validate_target_name(name)
        if fold(name) in originals:
            raise ValueError('Use a new destination name, not the original name of a selected item.')
    targets = [fold(names.get(str(source), source.name)) for source in sources]
    if len(set(targets)) != len(targets):
        raise ValueError('Two selected items cannot use the same destination name.')
    return names
