"""Read-only conflict reviews and explicit whole-item copy policies."""
from dataclasses import dataclass
import math
import stat
from .targets import validate_target_names


@dataclass(frozen=True)
class TransferItemState:
    size: int
    modified: float | None
    mode: int
    stamp: int | None = None
    identity: tuple | None = None
    reparse: bool = False

    @classmethod
    def from_stat(cls, attributes):
        modified = getattr(attributes, 'st_mtime', None)
        return cls(int(attributes.st_size or 0), float(modified) if modified is not None else None,
                   int(attributes.st_mode), getattr(attributes, 'st_mtime_ns', None),
                   (attributes.st_dev, attributes.st_ino) if hasattr(attributes, 'st_ino') else None,
                   bool(getattr(attributes, 'st_file_attributes', 0) & 0x400))

    @property
    def regular(self):
        return not self.reparse and stat.S_ISREG(self.mode)

    @property
    def directory(self):
        return not self.reparse and stat.S_ISDIR(self.mode)

    @property
    def kind(self):
        if self.reparse or stat.S_ISLNK(self.mode):
            return 'Link'
        if stat.S_ISDIR(self.mode):
            return 'Folder'
        return 'File' if self.regular else 'Other'


def local_transfer_metadata(paths):
    """lstat deliberately never follows a link for a Newer Only decision."""
    result = {}
    for path in paths:
        try:
            result[str(path)] = TransferItemState.from_stat(path.lstat())
        except FileNotFoundError:
            result[str(path)] = None
    return result


@dataclass(frozen=True)
class ConflictReview:
    sources: tuple
    source_states: dict
    target_states: dict
    destination: object
    source_panel: str
    target_panel: str
    connection: object

    def rows(self):
        return [(source.name, self.source_states[str(source)], self.target_states[str(source)])
                for source in self.sources if self.target_states[str(source)] is not None]

    def choose(self, policy, overrides=None):
        if policy not in ('replace', 'skip', 'newer', 'custom'):
            raise ValueError('Unknown conflict policy')
        overrides = dict(overrides or {})
        if set(overrides) - {str(source) for source in self.sources}:
            raise ValueError('A decision refers to an item outside this transfer.')
        chosen, renames = [], {}
        for source in self.sources:
            left, right = self.source_states[str(source)], self.target_states[str(source)]
            if left is None:
                raise FileNotFoundError('Source is no longer available: {}'.format(source.name))
            action, name = overrides.get(str(source), ('skip' if policy == 'custom' else policy, None))
            if action not in ('replace', 'skip', 'newer', 'rename'):
                raise ValueError('Unknown item conflict decision')
            if action == 'rename':
                if not left.regular:
                    raise ValueError('Rename destination currently supports regular files only.')
                renames[str(source)] = name
                chosen.append(source)
            elif right is None or action == 'replace':
                chosen.append(source)
            elif action == 'newer' and left.regular and right.regular:
                # Conservative tolerance for remote timestamp precision. A size
                # difference alone is NOT evidence that the source is newer.
                if (left.modified is not None and right.modified is not None and
                        math.isfinite(left.modified) and math.isfinite(right.modified) and
                        left.modified > right.modified + 2.0):
                    chosen.append(source)
        # Check against ALL selected original names, including skipped items,
        # so a renamed copy cannot accidentally take another item's old name.
        renames = validate_target_names(self.sources, renames, windows=self.target_panel == 'local')
        return ConflictDecision(tuple(chosen), self, policy, tuple(renames.items()))

    def validate(self, sources, source_states, target_states):
        for source in sources:
            key = str(source)
            if (source_states[key] != self.source_states[key] or
                    target_states[key] != self.target_states[key]):
                raise RuntimeError('Source or destination changed after confirmation: {}. '
                                   'Start the transfer again to review it.'.format(source.name))


@dataclass(frozen=True)
class ConflictDecision:
    sources: tuple
    review: ConflictReview
    policy: str
    renames: tuple = ()

    @property
    def target_names(self):
        return dict(self.renames)

    def validate(self, sources, source_states, target_states):
        renames = self.target_names
        for source in sources:
            key = str(source)
            expected_target = None if key in renames else self.review.target_states[key]
            if source_states[key] != self.review.source_states[key] or target_states[key] != expected_target:
                raise RuntimeError('Source or destination changed, or the renamed target already exists: {}. '
                                   'Start the transfer again to review it.'.format(source.name))
