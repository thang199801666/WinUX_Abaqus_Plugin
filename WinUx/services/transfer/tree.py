"""Bounded, read-only recursive copy planning. No links, deletes or mirror mode."""
from dataclasses import dataclass, field
from contextlib import contextmanager, ExitStack
import os
import math
from pathlib import Path, PurePosixPath
import time

from .conflicts import ConflictDecision, ConflictReview, TransferItemState
from .targets import validate_target_name


@dataclass(frozen=True)
class ScanLimits:
    entries: int = 10000
    depth: int = 32
    seconds: float = 30.0


class TreeReader:
    def __init__(self, side, server=None, sftp=None):
        self.side, self.server, self.sftp = side, server, sftp

    @contextmanager
    def session(self):
        if self.side == 'server' and self.sftp is None:
            # A cancelled Paramiko listdir_iter may retain its OPENDIR handle.
            # Closing this scan-local channel releases it without disturbing the
            # browser channel or the one authenticated SSH transport.
            with self.server._auxiliary_session() as (_, sftp):
                yield TreeReader(self.side, self.server, sftp)
        else:
            yield self

    def path(self, value):
        return Path(value) if self.side == 'local' else self.server.normalize(value)

    def stat(self, path):
        if self.side == 'server' and self.sftp is None:
            return self.server.transfer_path_metadata(path)
        try:
            return TransferItemState.from_stat(self.sftp.lstat(str(path)) if self.sftp is not None else Path(path).lstat())
        except OSError as exc:
            if exc.errno == 2:
                return None
            raise

    def listing(self, path, limit, check):
        if self.side == 'server':
            if self.sftp is None:
                return self.server.transfer_directory_metadata(path, limit=limit, check=check)
            return read_sftp_directory(self.sftp, path, limit=limit, check=check)
        result = {}
        with os.scandir(path) as entries:
            for entry in entries:
                check()
                if len(result) >= limit:
                    raise ValueError('Recursive review entry limit exceeded; select a smaller folder.')
                # Windows DirEntry.stat may report zero file IDs while lstat
                # reports the actual identity. Use one consistent source for
                # queued-snapshot comparison and reparse-point protection.
                result[entry.name] = TransferItemState.from_stat(Path(entry.path).lstat())
        return result


def read_sftp_directory(sftp, folder, *, limit, check):
    check()
    iterator = getattr(sftp, 'listdir_iter', None)
    entries = iterator(str(folder), read_aheads=1) if callable(iterator) else iter(sftp.listdir_attr(str(folder)))
    result = {}
    try:
        for entry in entries:
            check()
            if len(result) >= limit:
                raise ValueError('Recursive review entry limit exceeded; select a smaller folder.')
            result[entry.filename] = TransferItemState.from_stat(entry)
        check()
        return result
    finally:
        close = getattr(entries, 'close', None)
        if callable(close):
            close()


@dataclass(frozen=True)
class TreeReview(ConflictReview):
    original: ConflictReview = None
    relative_paths: dict = field(default_factory=dict)
    source_directories: dict = field(default_factory=dict)
    target_directories: dict = field(default_factory=dict)
    source_guards: dict = field(default_factory=dict)
    target_guards: dict = field(default_factory=dict)
    limits: ScanLimits = field(default_factory=ScanLimits)

    def display_name(self, source):
        name = str(self.relative_paths[str(source)])
        return name + '/' if self.source_states[str(source)].directory else name

    def choose(self, policy, overrides=None):
        overrides = dict(overrides or {})
        if set(overrides) - {str(source) for source in self.sources}:
            raise ValueError('A decision refers to an item outside this review.')
        chosen, renamed = [], {}
        fold = str.casefold if self.target_panel == 'local' else lambda value: value
        reserved = {fold(str(path)) for path in self.relative_paths.values()} | {
            fold(str(path)) for path in self.target_directories}
        outputs = set()
        for source in self.sources:
            key = str(source)
            single = ConflictReview((source,), self.source_states, self.target_states, self.destination,
                                    self.source_panel, self.target_panel, self.connection)
            decision = single.choose(policy, {key: overrides[key]} if key in overrides else None)
            if not decision.sources:
                continue
            relative = self.relative_paths[key]
            if decision.renames:
                name = decision.target_names[key]
                relative = relative.with_name(name)
                if fold(str(relative)) in reserved:
                    raise ValueError('The new name belongs to another selected item or folder.')
                renamed[key] = name
            output = fold(str(relative))
            if output in outputs:
                raise ValueError('Two reviewed items cannot have the same destination path.')
            outputs.add(output)
            chosen.append(source)
        return TreeDecision(tuple(chosen), self, policy, tuple(renamed.items()))

    def same_snapshot(self, other):
        if not all(getattr(self, key) == getattr(other, key) for key in (
            'sources', 'source_states', 'target_states', 'relative_paths', 'source_directories',
            'target_directories')):
            return False
        def guards(review, source):
            values = review.source_guards if source else review.target_guards
            return {path: (value if source and path in review.source_directories else
                           (value.mode, value.identity, value.reparse)) for path, value in values.items()}
        return guards(self, True) == guards(other, True) and guards(self, False) == guards(other, False)


@dataclass(frozen=True)
class TreeDecision(ConflictDecision):
    pass


def scan_tree(original, source_reader, target_reader, *, cancel=None, current=None, limits=None):
    limits = limits or ScanLimits()
    if (type(limits.entries) is not int or type(limits.depth) is not int or
            limits.entries < 1 or limits.depth < 1 or not math.isfinite(limits.seconds) or limits.seconds <= 0):
        raise ValueError('Recursive review limits must be positive.')
    if (cancel is not None and cancel.is_set()) or (current is not None and not current()):
        raise RuntimeError('Recursive review cancelled or server connection changed.')
    deadline = time.monotonic() + limits.seconds
    with ExitStack() as stack:
        source = stack.enter_context(source_reader.session())
        target = stack.enter_context(target_reader.session())
        return _scan_tree(original, source, target, cancel=cancel, current=current, limits=limits, deadline=deadline)


def _scan_tree(original, source_reader, target_reader, *, cancel=None, current=None, limits, deadline):
    def check():
        if (cancel is not None and cancel.is_set()) or (current is not None and not current()):
            raise RuntimeError('Recursive review cancelled or server connection changed.')
        if time.monotonic() >= deadline:
            raise TimeoutError('Recursive review timed out; select a smaller folder.')

    sources, left, right, relative_paths = [], {}, {}, {}
    source_dirs, target_dirs, source_guards, target_guards = {}, {}, {}, {}
    target_cache, target_nodes, seen, destinations = {}, {}, set(), set()
    destination = target_reader.path(original.destination)
    count, listed_count = 0, 0

    def listing(reader, path, limit):
        nonlocal listed_count
        result = reader.listing(path, min(limit, max(0, 2 * limits.entries - listed_count)), check)
        listed_count += len(result)
        check()
        return result

    def ancestors(reader, path, guards):
        for index, parent in enumerate((path, *path.parents)):
            check()
            if index > limits.depth + 32:
                raise ValueError('Path depth exceeds the recursive review limit.')
            if str(parent) not in guards:
                if len(guards) >= limits.entries + 64:
                    raise ValueError('Too many ancestor folders for a single recursive review.')
                state = reader.stat(parent)
                if state is None or not state.directory:
                    raise ValueError('Recursive review does not follow links or non-folder ancestors: {}'.format(parent))
                guards[str(parent)] = state

    ancestors(target_reader, destination, target_guards)
    target_nodes[PurePosixPath('.')] = target_guards[str(destination)]

    def target_state(relative):
        parent = relative.parent
        state = target_nodes.get(parent)
        if state is None:
            return None
        if not state.directory:
            raise ValueError('Destination parent is not a regular folder: {}'.format(parent))
        if parent not in target_cache:
            path = destination.joinpath(*parent.parts)
            fresh = target_reader.stat(path)
            if fresh != state:
                raise RuntimeError('Destination folder changed during the scan; review again.')
            target_guards[str(path)] = fresh
            target_cache[parent] = listing(target_reader, path, limits.entries)
        return target_cache[parent].get(relative.name)

    def visit(source, relative, state, depth):
        nonlocal count
        check()
        count += 1
        if count > limits.entries or depth > limits.depth:
            raise ValueError('Recursive review limit exceeded; select a smaller folder.')
        validate_target_name(relative.name)
        key = str(source)
        output = str(relative).casefold() if original.target_panel == 'local' else str(relative)
        if key in seen or output in destinations:
            raise ValueError('Overlapping selections or destination name collisions; select disjoint folders.')
        seen.add(key)
        destinations.add(output)
        if state is None or (not state.regular and not state.directory):
            raise ValueError('Links, junctions and special files are not followed in recursive review: {}'.format(source))
        target = target_state(relative)
        if target is not None and not ((state.directory and target.directory) or (state.regular and target.regular)):
            raise ValueError('File/folder/link type conflict needs manual review: {}'.format(relative))
        if state.directory:
            if source_reader.stat(source) != state:
                raise RuntimeError('Source folder changed during the scan; review again.')
            source_dirs[key] = relative
            source_guards[key] = state
            target_dirs[relative] = target
            target_nodes[relative] = target
            entries = listing(source_reader, source, limits.entries - count + 1)
            if entries:
                for name in sorted(entries, key=str.casefold):
                    validate_target_name(name)
                    visit(source / name, relative / name, entries[name], depth + 1)
                return
        elif state.size < 0:
            raise ValueError('Source file has invalid size metadata.')
        sources.append(source)
        left[key], right[key], relative_paths[key] = state, target, relative

    for source in original.sources:
        check()
        source = source_reader.path(source)
        ancestors(source_reader, source.parent, source_guards)
        visit(source, PurePosixPath(validate_target_name(source.name)), source_reader.stat(source), 1)
    check()
    return TreeReview(tuple(sources), left, right, destination, original.source_panel,
                      original.target_panel, original.connection, original, relative_paths,
                      source_dirs, target_dirs, source_guards, target_guards, limits)
