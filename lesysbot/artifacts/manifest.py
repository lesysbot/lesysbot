"""Package metadata — README frontmatter + package discovery.

Metadata comes from the README frontmatter and filenames only; package code is
**never imported** here (importing would execute arbitrary code before the user
has consented to the install).

Every frontmatter key is optional, and a package with no README at all still
installs. That is deliberate: the frontmatter describes a package *better*, it
is never the thing that makes it work. It means every tool package written
before dashboards, prerequisites or `preserve:` existed keeps installing with
no edit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from lesysbot.artifacts.kinds import (
    DASHBOARD_MARKERS,
    DEFAULT_KIND,
    ArtifactKind,
    parse_kind,
)

# Loader-compatible package names: the registry ignores dirs starting with `.`/`_`.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n(.*?)\n\s*---\s*(?:\n|\Z)", re.DOTALL)

# Subdirectories that are never packages.
_SKIP_DIRS = ("__pycache__", "tests", "docs")

# Collection repos group packages under one of these; checked in order.
_COLLECTION_DIRS = ("tools", "dashboards")


def parse_frontmatter(text: str) -> dict:
    """YAML frontmatter (leading ``---`` block) as a dict; ``{}`` on any failure."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _as_list(value) -> list[str]:
    """Frontmatter lists, forgiving about a bare scalar (``requires: psql``)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None]
    return [str(value)]


def _parse_prerequisites(value) -> list[tuple[str, str]]:
    """``prerequisites:`` → ``[(type, value), …]``.

    Accepts the compact one-key mapping form the docs use::

        prerequisites:
          - gpu: nvidia
          - service: prometheus

    and the explicit form ``{type: gpu, value: nvidia}``. Anything unrecognized
    is dropped rather than raising — a manifest from a newer LeSysBot must not
    make a package uninstallable on an older one.
    """
    out: list[tuple[str, str]] = []
    for entry in _as_list_of_mappings(value):
        if "type" in entry:
            kind, val = entry.get("type"), entry.get("value", "")
        elif len(entry) == 1:
            (kind, val), = entry.items()
        else:
            continue
        if kind:
            out.append((str(kind).strip().lower(), str(val).strip()))
    return out


def _as_list_of_mappings(value) -> list[dict]:
    if isinstance(value, dict):
        return [{k: v} for k, v in value.items()]
    if isinstance(value, (list, tuple)):
        return [e for e in value if isinstance(e, dict)]
    return []


@dataclass
class ArtifactPackage:
    """A folder package found in an extracted archive (or on disk)."""

    path: Path
    name: str
    kind: ArtifactKind = DEFAULT_KIND
    description: str = ""
    version: str | None = None
    tool_files: list[str] = field(default_factory=list)
    has_requirements: bool = False
    # Gating, mirroring what `@tool` already accepts so a package README and its
    # code can state the same thing.
    platforms: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    # Richer checks (gpu/service/metric/docker/…), resolved by lesysbot.prereq.
    prerequisites: list[tuple[str, str]] = field(default_factory=list)
    # pip requirements, merged with any requirements.txt at install time.
    requires_python: list[str] = field(default_factory=list)
    # Paths inside the package that an update must not overwrite.
    preserve: list[str] = field(default_factory=list)



def _qualifies(directory: Path) -> bool:
    """True when *directory* looks like an installable package.

    Either it directly contains a non-underscore ``.py`` file — the same rule the
    registry loader uses for a tool package — or it carries a dashboard payload.
    A dashboard may be a lone ``dashboard.json`` with no Python at all, so the
    marker check is what lets such a folder be discovered.
    """
    if any(p.suffix == ".py" and not p.name.startswith("_")
           for p in directory.iterdir() if p.is_file()):
        return True
    return any((directory / marker).is_file() for marker in DASHBOARD_MARKERS)


def _detect_kind(directory: Path, declared: str | None) -> ArtifactKind:
    """Resolve a package's kind: explicit frontmatter, else the payload.

    The payload is consulted second but is authoritative when the frontmatter is
    silent — a folder holding ``dashboard.json`` is a dashboard whether or not
    its author remembered to say so, which keeps a plain Grafana export (the
    most likely thing someone drops in a repo) installable as-is.
    """
    kind = parse_kind(declared)
    if kind is not None:
        return kind
    if any((directory / marker).is_file() for marker in DASHBOARD_MARKERS):
        return ArtifactKind.DASHBOARD
    return DEFAULT_KIND


def _package_from(directory: Path, default_name: str) -> ArtifactPackage:
    fm: dict = {}
    readme = directory / "README.md"
    if readme.is_file():
        fm = parse_frontmatter(readme.read_text(encoding="utf-8", errors="replace"))
    version = fm.get("version")
    return ArtifactPackage(
        path=directory,
        name=str(fm.get("name") or default_name),
        kind=_detect_kind(directory, fm.get("kind")),
        description=str(fm.get("description") or ""),
        version=str(version) if version is not None else None,
        tool_files=sorted(
            p.name
            for p in directory.iterdir()
            if p.is_file() and p.suffix == ".py" and not p.name.startswith("_")
        ),
        has_requirements=(directory / "requirements.txt").is_file(),
        platforms=[p.lower() for p in _as_list(fm.get("platforms"))],
        requires=_as_list(fm.get("requires")),
        prerequisites=_parse_prerequisites(fm.get("prerequisites")),
        requires_python=_as_list(fm.get("requires_python")),
        preserve=_as_list(fm.get("preserve")),
    )


def discover_packages(root: Path, default_name: str) -> list[ArtifactPackage]:
    """Find packages in an extracted tree.

    *root* itself is the package when it directly holds a payload (single-package
    repo, named *default_name*); otherwise packages are the qualifying immediate
    subdirectories of ``root/tools`` or ``root/dashboards`` when either yields
    any — collection repos group them that way, like the core repo — else of
    *root* itself.

    A collection may hold both, and both are returned: one repo, one install
    command, tools and dashboards each routed by their own kind.
    """
    if _qualifies(root):
        return [_package_from(root, default_name)]

    grouped: list[ArtifactPackage] = []
    for name in _COLLECTION_DIRS:
        sub = root / name
        if sub.is_dir():
            grouped.extend(_scan_subdirs(sub))
    if grouped:
        return grouped
    return _scan_subdirs(root)


def _scan_subdirs(root: Path) -> list[ArtifactPackage]:
    packages = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        if sub.name.startswith((".", "_")) or sub.name in _SKIP_DIRS:
            continue
        if _qualifies(sub):
            packages.append(_package_from(sub, sub.name))
    return packages
