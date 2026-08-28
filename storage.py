"""Crash-safe JSON persistence for the on-disk caches.

Every cache here is written by a long-running server that gets killed to
restart it (see aiss.sh). A plain open(path, 'w') truncates the file before the
new JSON lands, so a kill inside that window leaves a half-written file that
fails to parse on the next boot — the whole cache is lost. Writing a sibling
temp file and renaming it into place makes the rename the only visible step,
and on POSIX that step is atomic: readers see the complete old file or the
complete new one, never a partial one.
"""

import json
import os
import tempfile


def write_json_atomic(path, data, indent=2):
    """Serialize data to path atomically. Returns True on success.

    The temp file is a sibling of the target so the rename stays within one
    filesystem; a rename across filesystems is not atomic and would fail.
    """
    directory = os.path.dirname(os.path.abspath(path))
    prefix = f'.{os.path.basename(path)}-'
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            'w', dir=directory, prefix=prefix, suffix='.tmp', delete=False
        ) as f:
            tmp_path = f.name
            json.dump(data, f, indent=indent)
            # Serialization errors surface above the rename, leaving the
            # existing file untouched rather than replaced by a bad one.
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
        return True
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
