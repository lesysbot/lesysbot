"""The versioned JSON lock recording what is installed and where it came from.

``~/.lesysbot/lesysbot.lock.json``::

    {"version": 2, "artifacts": {"tool:cpu-temp": {kind, repo, commit, …}}}

Entries are keyed ``<kind>:<name>`` so a dashboard and a tool may share a name
without colliding — "postgres" is a plausible name for both, and the two land in
different directories, so nothing else would stop it.

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

from lesysbot.artifacts.kinds import DEFAULT_KIND, ArtifactKind

logger = logging.getLogger(__name__)

# Root key of the current lock file.
LOCK_KEY = "artifacts"
LOCK_VERSION = 2

LOCK_NAME = "lesysbot.lock.json"


def entry_key(kind: ArtifactKind | str, name: str) -> str:
    """The lock key for a package. ``kind`` may be the enum or its value."""
    return f"{ArtifactKind(kind).value}:{name}"


class JsonState:
    """A ``{"version": N, "<root_key>": {...}}`` JSON file.

    Generic and version-agnostic: *version* is whatever the caller stamps.
    ``ArtifactLock`` passes ``LOCK_VERSION``; the default stays 1 so this class
    keeps behaving as it always did for anything else that uses it.
    """

    def __init__(self, path: Path, root_key: str, version: int = 1) -> None:
        self.path = Path(path)
        self.root_key = root_key
        self.version = version

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
        payload = {"version": self.version, self.root_key: items}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


class ArtifactLock:
    """The artifact lock, with one-time migration from the v1 tools lock."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._state = JsonState(self.path, LOCK_KEY, LOCK_VERSION)

    # -- reading --------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Every entry, keyed ``<kind>:<name>``."""
        return self._state.load()

    def get(self, kind: ArtifactKind | str, name: str) -> dict[str, Any] | None:
        return self.load().get(entry_key(kind, name))

    def of_kind(self, kind: ArtifactKind | str) -> dict[str, dict[str, Any]]:
        """Entries of one kind, keyed by bare name."""
        want = ArtifactKind(kind).value
        return {
            entry.get("name") or key.split(":", 1)[-1]: entry
            for key, entry in self.load().items()
            if entry.get("kind", DEFAULT_KIND.value) == want
        }

    # -- writing --------------------------------------------------------------

    def save(self, items: dict[str, Any]) -> None:
        self._state.save(items)

    def put(self, kind: ArtifactKind | str, name: str, entry: dict[str, Any]) -> None:
        items = self.load()
        items[entry_key(kind, name)] = entry
        self.save(items)

    def drop(self, names: list[str], kind: ArtifactKind | str | None = None) -> list[str]:
        """Drop *names*, returning the bare names that were present.

        With no *kind*, a bare name drops every kind sharing it — that is what
        ``lesysbot remove <name>`` means once the caller has already resolved
        which package it is deleting.
        """
        items = self.load()
        kinds = [ArtifactKind(kind)] if kind is not None else list(ArtifactKind)
        dropped: list[str] = []
        for name in names:
            for k in kinds:
                if items.pop(entry_key(k, name), None) is not None:
                    dropped.append(name)
        if dropped:
            self.save(items)
        return dropped


def drop_entries(path: Path, names: list[str],
                 kind: ArtifactKind | str | None = None) -> list[str]:
    """Drop *names* from the lock at *path*; returns the ones that were present.

    Keeps the lock in sync when an installed package is deleted
    (``lesysbot remove``).
    """
    return ArtifactLock(Path(path)).drop(names, kind)
