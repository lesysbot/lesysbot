"""What kind of thing an installable package is.

LeSysBot installs two kinds of package from GitHub, and they differ only in
where they land and what has to be true for them to work:

* a **tool** gives the bot a new ability, and lands in ``mcp.tools_dir``;
* a **dashboard** gives Grafana a new page, and lands in the stack's
  ``installed/`` directory.

Everything else — fetching, extraction, consent, provenance, updates — is
identical, which is why there is one installer rather than two.

The kind is read from the package's README frontmatter. It is *optional*: a
package without one is a tool, so every tool package written before this existed
keeps installing unchanged. When the frontmatter is silent, the payload decides —
a folder holding ``dashboard.json``/``dashboard.py`` is a dashboard whatever its
README says about itself.
"""

from __future__ import annotations

from enum import Enum


class ArtifactKind(str, Enum):
    """A kind of installable package. ``str`` so it serializes into the lock."""

    TOOL = "tool"
    DASHBOARD = "dashboard"

    @property
    def label(self) -> str:
        """Singular human name, for CLI and panel text."""
        return self.value

    @property
    def plural(self) -> str:
        return f"{self.value}s"


# Filenames that make a folder a dashboard regardless of what its README claims.
DASHBOARD_MARKERS = ("dashboard.json", "dashboard.py")

DEFAULT_KIND = ArtifactKind.TOOL


def parse_kind(value: str | None) -> ArtifactKind | None:
    """An explicit ``kind:`` from frontmatter, or None when absent/unrecognized.

    Unknown values return None rather than raising: frontmatter is written by
    other people, and a package from the future declaring ``kind: pack`` should
    fall through to payload detection instead of failing the whole install with
    a parse error.
    """
    if not value:
        return None
    try:
        return ArtifactKind(str(value).strip().lower())
    except ValueError:
        return None
