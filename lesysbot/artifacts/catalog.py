"""The marketplace index — display metadata, never a resolver.

LeSysBot installs from GitHub links and nothing else. The catalog exists so a
user can *find* something without already knowing its URL; every entry carries a
``source`` that is an ordinary github.com link, and installing one goes through
the same :func:`~lesysbot.artifacts.spec.parse_source` and the same consent
prompt as a link typed by hand.

That distinction is the whole trust model. There is no server that decides what
you may install, no opaque artifact, and nothing you cannot read before you run
it — the catalog just saves you a search.

Sources, in order: an explicit path, the refreshed copy in ``~/.lesysbot``, then
the copy bundled in the wheel. The bundled copy is why `lesysbot search` works
on a machine that has never been online.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from lesysbot.artifacts.kinds import DEFAULT_KIND, ArtifactKind, parse_kind
from lesysbot.core.paths import bundled_dir, user_dir

logger = logging.getLogger(__name__)

CATALOG_URL = "https://lesysbot.github.io/catalog.json"
CATALOG_NAME = "catalog.json"
CATALOG_VERSION = 1

_FETCH_TIMEOUT = 10.0


@dataclass(frozen=True)
class CatalogEntry:
    """One marketplace listing."""

    id: str
    name: str
    source: str
    kind: ArtifactKind = DEFAULT_KIND
    description: str = ""
    homepage: str = ""
    platforms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    official: bool = False

    def runs_here(self) -> bool:
        """Whether this entry's declared platforms include the current OS."""
        if not self.platforms:
            return True
        from lesysbot.core.host import current_os

        return current_os() in self.platforms

    def matches(self, query: str) -> bool:
        if not query:
            return True
        q = query.lower()
        haystack = " ".join([self.id, self.name, self.description,
                             self.source, *self.tags]).lower()
        return q in haystack


@dataclass
class Catalog:
    entries: list[CatalogEntry] = field(default_factory=list)
    source_path: Path | None = None
    updated: str = ""

    def find(self, ident: str) -> CatalogEntry | None:
        """An entry by id, or by exact name as a fallback."""
        key = (ident or "").strip().lower()
        for entry in self.entries:
            if entry.id.lower() == key:
                return entry
        for entry in self.entries:
            if entry.name.lower() == key:
                return entry
        return None

    def search(self, query: str = "", *, kind: str | None = None,
               here_only: bool = False) -> list[CatalogEntry]:
        out = [e for e in self.entries if e.matches(query)]
        if kind:
            want = ArtifactKind(kind)
            out = [e for e in out if e.kind is want]
        if here_only:
            out = [e for e in out if e.runs_here()]
        # Official first, then alphabetical — a newcomer searching "temperature"
        # should meet the maintained collection before somebody's fork of it.
        return sorted(out, key=lambda e: (not e.official, e.id))


def _entry_from(raw: dict) -> CatalogEntry | None:
    source = str(raw.get("source") or "").strip()
    ident = str(raw.get("id") or "").strip()
    if not source or not ident:
        return None
    return CatalogEntry(
        id=ident,
        name=str(raw.get("name") or ident),
        source=source,
        kind=parse_kind(raw.get("kind")) or DEFAULT_KIND,
        description=str(raw.get("description") or ""),
        homepage=str(raw.get("homepage") or ""),
        platforms=tuple(str(p).lower() for p in raw.get("platforms") or ()),
        tags=tuple(str(t) for t in raw.get("tags") or ()),
        official=bool(raw.get("official")),
    )


def parse_catalog(data: dict, path: Path | None = None) -> Catalog:
    """Build a Catalog from parsed JSON, dropping entries that make no sense.

    Malformed entries are skipped rather than fatal: a catalog is fetched from
    the network, and one bad row must not take `lesysbot search` down.
    """
    raw_entries = data.get("entries") if isinstance(data, dict) else None
    entries = []
    for raw in raw_entries or []:
        if isinstance(raw, dict):
            entry = _entry_from(raw)
            if entry is not None:
                entries.append(entry)
    return Catalog(entries=entries, source_path=path,
                   updated=str((data or {}).get("updated") or ""))


def _read(path: Path) -> Catalog | None:
    try:
        return parse_catalog(json.loads(path.read_text(encoding="utf-8")), path)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Ignoring unreadable catalog %s (%s)", path, e)
        return None


def cached_path() -> Path:
    return user_dir() / CATALOG_NAME


def bundled_path() -> Path:
    return bundled_dir() / CATALOG_NAME


def load_catalog(path: Path | None = None) -> Catalog:
    """The best catalog available, preferring fresher sources."""
    for candidate in (path, cached_path(), bundled_path()):
        if candidate and Path(candidate).is_file():
            catalog = _read(Path(candidate))
            if catalog is not None:
                return catalog
    return Catalog()


def refresh(url: str = CATALOG_URL, dest: Path | None = None) -> tuple[Catalog, str | None]:
    """Fetch the published catalog and cache it. Returns ``(catalog, error)``.

    A failed refresh is not an error the caller has to handle — it falls back to
    whatever was already there, so being offline degrades discovery instead of
    breaking it.
    """
    dest = Path(dest) if dest else cached_path()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _agent()})
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT) as response:
            payload = response.read()
        data = json.loads(payload)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return load_catalog(), f"could not refresh the catalog ({e})"

    catalog = parse_catalog(data, dest)
    if not catalog.entries:
        return load_catalog(), "the published catalog had no usable entries"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return catalog, None


def _agent() -> str:
    from lesysbot import __version__

    return f"lesysbot/{__version__}"
