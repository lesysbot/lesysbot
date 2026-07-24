"""The versioned JSON lock file for installed tool packages (`tools.lock.json`).

Atomic writes (tmp + ``os.replace``); a corrupt file is backed up as ``.bad``
and treated as empty rather than aborting — mirroring the registry's
``load_state()`` resilience.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Root key of the lock file: {"version": 1, "tools": {...}}.
LOCK_KEY = "tools"


class JsonState:
    """A ``{"version": 1, "<root_key>": {...}}`` JSON file."""

    def __init__(self, path: Path, root_key: str) -> None:
        self.path = Path(path)
        self.root_key = root_key

    def load(self) -> dict[str, Any]:
        """Return the ``root_key`` mapping; ``{}`` when missing or corrupt."""
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = data.get(self.root_key, {}) if isinstance(data, dict) else None
            if not isinstance(items, dict):
                raise ValueError(f"expected a {self.root_key!r} object")
            return items
        except Exception as e:
            backup = self.path.with_name(self.path.name + ".bad")
            try:
                os.replace(self.path, backup)
                logger.warning("Corrupt %s (%s) — backed up to %s", self.path, e, backup)
            except OSError:
                logger.warning("Corrupt %s (%s) — ignoring it", self.path, e)
            return {}

    def save(self, items: dict[str, Any]) -> None:
        payload = {"version": 1, self.root_key: items}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


def drop_entries(path: Path, names: list[str], root_key: str = LOCK_KEY) -> list[str]:
    """Drop *names* from the lock file, returning the ones that were present.

    Keeps the lock in sync when an installed package is deleted
    (``lesysbot tools remove``).
    """
    state = JsonState(Path(path), root_key)
    items = state.load()
    dropped = [n for n in names if n in items]
    for n in dropped:
        del items[n]
    if dropped:
        state.save(items)
    return dropped
