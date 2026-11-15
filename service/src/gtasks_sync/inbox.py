"""The Inbox: captures from other programs, one JSON file each (ADR 0004).

A caller writes `<name>.json.part`, renames it to `<name>.json`, then touches `queue/sync-now`.
Each file becomes a `create` op in the queue at the start of a round.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from gtasks_sync.queue import mint_local_id, write_op

log = logging.getLogger(__name__)


class InvalidCapture(Exception):
    """The file can never become a task."""


def parse_capture(path: Path) -> str:
    """The task title in an inbox file. Unknown fields are ignored, so callers can add fields."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InvalidCapture(f"unreadable: {e}") from e
    if not isinstance(raw, dict):
        raise InvalidCapture("not an object")
    text = raw.get("text")
    # Strip as the extension does, so the op passes parse_op.
    title = text.strip() if isinstance(text, str) else ""
    if not title:
        raise InvalidCapture("text must be a non-empty string")
    return title


class Inbox:
    def __init__(self, dir: Path) -> None:
        self.dir = dir
        self.failed_dir = dir / "failed"
        # Files whose op is in the queue but whose delete failed. Without this, each round makes the task again.
        # Only for this process: a restart can make one more copy.
        self._stuck: set[str] = set()

    def files(self) -> list[Path]:
        """Inbox files in name order. Other names, for example `*.json.part`, are not finished."""
        return sorted(p for p in self.dir.glob("*.json") if p.is_file())

    def failed(self) -> list[Path]:
        return sorted(p for p in self.failed_dir.glob("*.json") if p.is_file())

    def ingest(self, queue_dir: Path, now: datetime) -> None:
        """Turn each inbox file into a `create` op. One bad file does not stop the others."""
        now_ms = int(now.timestamp() * 1000)
        for path in self.files():
            if path.name in self._stuck:
                continue
            try:
                title = parse_capture(path)
            except FileNotFoundError:
                continue
            except InvalidCapture as e:
                # Permanent: in the inbox, it would log every round.
                log.warning("failed inbox file %s: %s", path.name, e)
                self._fail(path)
                continue

            op = {"op": "create", "task": mint_local_id(now_ms), "title": title, "notes": "", "due": None}
            try:
                write_op(queue_dir, op, now_ms)
            except OSError:
                # Maybe temporary, for example a full disk. The file stays, and the next round tries again.
                log.exception("cannot queue inbox file %s", path.name)
                return
            # Only after the op is in the queue. A crash before this line makes a second copy. Accepted (ADR 0004).
            try:
                path.unlink()
            except OSError:
                log.exception("cannot remove inbox file %s: skipped until restart", path.name)
                self._stuck.add(path.name)

    def _fail(self, path: Path) -> None:
        try:
            self.failed_dir.mkdir(exist_ok=True)
            os.replace(path, self.failed_dir / path.name)
        except OSError:
            log.exception("cannot move inbox file %s to failed: skipped until restart", path.name)
            self._stuck.add(path.name)
