"""Execute only the reviewed leaf files/empty folders; never rescan-and-copy extras."""
from pathlib import Path
from collections import OrderedDict

from .conflicts import TransferItemState
from .tree import TreeDecision


class DirectoryChecks:
    """Cache ancestor lookup chains, never the results of filesystem checks."""
    MAX_CHAINS = 128

    def __init__(self, guards, *, local, state, cancelled):
        self.guards = dict(guards)
        self.local, self.state, self.cancelled = local, state, cancelled
        self._chains = OrderedDict()

    def register(self, path, expected):
        self.guards[str(path)] = expected
        self._chains.clear()

    def check(self, child=None):
        if child is None:
            chain = self.guards.items()
        else:
            key = str(child.parent)
            chain = self._chains.get(key)
            if chain is None:
                chain = tuple((str(parent), self.guards[str(parent)]) for parent in child.parents
                              if str(parent) in self.guards)
                self._chains[key] = chain
                if len(self._chains) > self.MAX_CHAINS:
                    self._chains.popitem(last=False)
            else:
                self._chains.move_to_end(key)
        for path, expected in chain:
            self.cancelled()
            actual = self.state(path, self.local)
            if (actual is None or not actual.directory or
                    (expected.identity is not None and actual.identity != expected.identity)):
                raise RuntimeError('Folder or ancestor changed; recursive copy stopped: {}'.format(path))


def copy_reviewed_tree(model, decision, *, upload, cancel=None, progress=None, preserve_timestamps=False):
    if not isinstance(decision, TreeDecision):
        raise ValueError('A recursive copy requires an explicit reviewed plan.')
    review = decision.review
    if (review.source_panel, review.target_panel) != (('local', 'server') if upload else ('server', 'local')):
        raise ValueError('Recursive copy direction does not match its review.')
    destination = model.normalize(review.destination) if upload else Path(review.destination)
    names = decision.target_names
    required = set()
    for source in decision.sources:
        relative = review.relative_paths[str(source)]
        if review.source_states[str(source)].directory:
            required.add(relative)
        required.update(parent for parent in relative.parents if parent.parts)
    total = sum(review.source_states[str(source)].size for source in decision.sources
                if review.source_states[str(source)].regular)
    overall_done = 0

    with model._auxiliary_session() as (client, sftp):
        def state(path, local):
            try:
                attr = Path(path).lstat() if local else sftp.lstat(str(path))
                return TransferItemState.from_stat(attr)
            except OSError as exc:
                if exc.errno == 2:
                    return None
                raise

        # Directory mtimes change as our own children are created, so runtime
        # ancestor checks use no-link/type and local filesystem identity. The
        # controller separately checks the full snapshot before any writes.
        source_checks = DirectoryChecks(review.source_guards, local=upload, state=state,
                                         cancelled=lambda: model._cancelled(cancel))
        target_checks = DirectoryChecks(review.target_guards, local=not upload, state=state,
                                         cancelled=lambda: model._cancelled(cancel))
        source_checks.check()
        target_checks.check()
        for relative in sorted(required, key=lambda path: (len(path.parts), str(path))):
            model._cancelled(cancel)
            path = destination.joinpath(*relative.parts)
            target_checks.check(path)
            expected = review.target_directories[relative]
            if expected is None:
                # Never merge into an unreviewed folder that appeared since
                # confirmation. No exist_ok/recursive mkdir through ancestors.
                if upload:
                    sftp.mkdir(str(path))
                else:
                    path.mkdir()
                actual = state(path, not upload)
                if actual is None or not actual.directory:
                    raise RuntimeError('Could not create the reviewed destination folder.')
            else:
                actual = state(path, not upload)
                if actual is None or not actual.directory or (
                        expected.identity is not None and actual.identity != expected.identity):
                    raise RuntimeError('Destination folder changed; recursive copy stopped.')
            target_checks.register(path, actual)

        for source in decision.sources:
            model._cancelled(cancel)
            key = str(source)
            relative = review.relative_paths[key]
            if key in names:
                relative = relative.with_name(names[key])
            target = destination.joinpath(*relative.parts)
            expected_source = review.source_states[key]
            expected_target = None if key in names else review.target_states[key]
            label = review.display_name(source)
            current_done = 0
            current_total = expected_source.size if expected_source.regular else 0

            def guard():
                model._cancelled(cancel)
                source_checks.check(source)
                target_checks.check(target)
                if state(source, upload) != expected_source:
                    raise RuntimeError('Source changed after recursive review: {}'.format(label))
                if expected_source.regular and state(target, not upload) != expected_target:
                    raise RuntimeError('Destination changed after recursive review: {}'.format(label))

            def advance(amount):
                nonlocal current_done, overall_done
                current_done += amount
                overall_done += amount
                if progress:
                    progress(label, current_done, current_total, overall_done, total)

            if progress:
                progress(label, 0, current_total, overall_done, total)
            guard()
            if expected_source.regular:
                no_replace = expected_target is None
                if upload:
                    if current_total >= model.STREAM_FILE_THRESHOLD:
                        model._upload_file_stream(source, target, cancel=cancel, advance=advance,
                            sftp_client=sftp, client=client, no_replace=no_replace, before_publish=guard,
                            preserve_timestamps=preserve_timestamps)
                    else:
                        model._upload_small_file_atomic(source, target, cancel, advance, sftp,
                            client=client, no_replace=no_replace, before_publish=guard,
                            preserve_timestamps=preserve_timestamps)
                else:
                    model._download_file(source, target, cancel=cancel, advance=advance,
                        sftp_client=sftp, client=client, no_replace=no_replace,
                        private_scratch=True, before_publish=guard, preserve_timestamps=preserve_timestamps)
            if progress:
                progress(label, current_done, current_total, overall_done, total)
