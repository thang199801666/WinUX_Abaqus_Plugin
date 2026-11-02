"""Bounded, per-connection POSIX identity lookup for remote directory rows."""
from collections import OrderedDict
import time


class RemoteIdentityNames:
    MAX_ENTRIES = 2048
    BATCH_SIZE = 64
    NAME_TTL = 300
    MISSING_TTL = 60

    def __init__(self):
        self._cache = OrderedDict()

    def resolve(self, uids, gids, lookup):
        now = time.monotonic()
        requested = [(kind, value) for kind, values in (('user', uids), ('group', gids))
                     for value in sorted({value for value in values
                                          if isinstance(value, int) and value >= 0})]
        result, missing = {}, []
        for key in requested:
            cached = self._cache.get(key)
            if cached is not None and cached[0] > now:
                self._cache.move_to_end(key)
                result[key] = cached[1]
            else:
                missing.append(key)
        for offset in range(0, len(missing), self.BATCH_SIZE):
            batch = missing[offset:offset + self.BATCH_SIZE]
            commands = []
            for kind, database, marker in (('user', 'passwd', '__WINUX_USERS__'),
                                            ('group', 'group', '__WINUX_GROUPS__')):
                ids = [str(value) for key_kind, value in batch if key_kind == kind]
                commands.append("printf '%s\\n' '{}'".format(marker))
                if ids:
                    # Only validated integer IDs enter the command, never file
                    # names. getent respects LDAP/NIS/NSS as well as local files.
                    commands.append('getent {} {} 2>/dev/null || :'.format(database, ' '.join(ids)))
            try:
                output = lookup('; '.join(commands))
            except Exception:
                # Identity metadata must not prevent directory browsing.
                output = ''
            found, kind = {}, None
            for line in str(output or '').splitlines():
                if line == '__WINUX_USERS__':
                    kind = 'user'
                elif line == '__WINUX_GROUPS__':
                    kind = 'group'
                elif kind:
                    fields = line.split(':')
                    if len(fields) >= 3 and fields[0] and fields[2].isdigit():
                        key = (kind, int(fields[2]))
                        if key in batch:
                            found[key] = fields[0]
            for key in batch:
                name = found.get(key, '')
                result[key] = name
                self._cache[key] = (now + (self.NAME_TTL if name else self.MISSING_TTL), name)
                self._cache.move_to_end(key)
                while len(self._cache) > self.MAX_ENTRIES:
                    self._cache.popitem(last=False)
        return ({value: result.get(('user', value), '') for value in uids},
                {value: result.get(('group', value), '') for value in gids})
