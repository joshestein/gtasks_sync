import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_atomic(path: Path, obj: Any, *, durable: bool) -> None:
    """Replace path with obj as JSON. Readers see the old file or the new file, never a partial one.

    durable: also flush the file and the rename to the drive, so they survive a power loss.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
            if durable:
                f.flush()
                _full_fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    if not durable:
        return
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        _full_fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _full_fsync(fd: int) -> None:
    """On macOS, fsync() does not flush the drive's cache. F_FULLFSYNC does."""
    try:
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
    except OSError:
        os.fsync(fd)  # Not supported by this file system.
