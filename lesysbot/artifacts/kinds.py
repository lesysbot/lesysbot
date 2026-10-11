"""What kind of thing an installable package is.

Today that is only a **tool**: it gives the bot a new ability and lands in
``mcp.tools_dir``. Dashboards used to be a second kind; LeSysBot now has exactly
one dashboard, generated for the machine, and a user changes it by editing their
own copy (``lesysbot dashboard customize``) rather than installing another.

The enum stays because it namespaces the lock file — entries are keyed
``tool:<name>`` — and an older lock may still hold ``dashboard:<name>`` rows,
which :func:`parse_kind` reads as "not something this version installs".
"""

from __future__ import annotations

from enum import Enum


class ArtifactKind(str, Enum):
    """A kind of installable package. ``str`` so it serializes into the lock."""

    TOOL = "tool"

    @property
    def label(self) -> str:
        """Singular human name, for CLI and panel text."""
        return self.value

    @property
    def plural(self) -> str:
        return f"{self.value}s"


# Files that mark a folder as a Grafana dashboard. Such a folder is not
# installable; the installer says how to use it as the dashboard instead.
DASHBOARD_MARKERS = ("dashboard.json", "dashboard.py")

DEFAULT_KIND = ArtifactKind.TOOL


def parse_kind(value: str | None) -> ArtifactKind | None:
    """An explicit ``kind:`` from frontmatter, or None when absent/unrecognized.

    Unknown values return None rather than raising: frontmatter is written by
    other people, and a package declaring a kind this version doesn't know
    should fall through to payload detection instead of failing the whole
    install with a parse error.
    """
    if not value:
        return None
    try:
        return ArtifactKind(str(value).strip().lower())
    except ValueError:
        return None
