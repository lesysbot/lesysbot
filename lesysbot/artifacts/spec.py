"""Source-spec grammar for tool installs.

Accepted forms::

    owner/repo
    owner/repo@ref                      # branch, tag, or commit SHA
    owner/repo/sub/dir[@ref]            # a package inside a bigger repo
    https://github.com/owner/repo[.git]
    https://github.com/owner/repo/tree/REF[/sub/dir]
    git@github.com:owner/repo[.git]

Branch names containing ``/`` are ambiguous in ``/tree/`` URLs (GitHub resolves
them server-side; we can't) — use the ``owner/repo/subdir@feature/x`` short form
for those.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from lesysbot.artifacts.errors import SpecError

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class ToolSource:
    owner: str
    repo: str
    subdir: str | None = None
    ref: str | None = None

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    def __str__(self) -> str:
        text = self.slug
        if self.subdir:
            text += f"/{self.subdir}"
        if self.ref:
            text += f"@{self.ref}"
        return text


def _check_segment(kind: str, value: str, spec: str) -> str:
    if not _NAME_RE.match(value):
        raise SpecError(f"Invalid {kind} {value!r} in spec {spec!r}")
    return value


def _check_subdir(parts: list[str], spec: str) -> str | None:
    for part in parts:
        if not part or part in (".", "..") or part.startswith(".") or "\\" in part:
            raise SpecError(f"Invalid path segment {part!r} in spec {spec!r}")
    return "/".join(parts) or None


def parse_source(spec: str) -> ToolSource:
    """Parse a GitHub tool source spec into a :class:`ToolSource`."""
    text = spec.strip()
    if not text:
        raise SpecError("Empty tool source spec")

    # git@github.com:owner/repo[.git] → treat like a URL path.
    if text.startswith("git@"):
        host, _, path = text[4:].partition(":")
        if host.lower() != "github.com":
            raise SpecError(f"Only github.com sources are supported, got {host!r}")
        return _from_path_segments(path, spec, allow_tree=False)

    if text.startswith(("http://", "https://")):
        url = urlparse(text)
        if url.hostname not in ("github.com", "www.github.com"):
            raise SpecError(f"Only github.com URLs are supported, got {url.hostname!r}")
        return _from_path_segments(url.path, spec, allow_tree=True)

    # Short form: owner/repo[/subdir...][@ref]
    ref: str | None = None
    if "@" in text:
        text, _, ref_part = text.rpartition("@")
        ref = ref_part.strip()
        if not ref or any(c.isspace() for c in ref):
            raise SpecError(f"Invalid ref in spec {spec!r}")
    parts = [p for p in text.split("/")]
    if len(parts) < 2:
        raise SpecError(
            f"Expected owner/repo (optionally /subdir and @ref), got {spec!r}"
        )
    owner = _check_segment("owner", parts[0], spec)
    repo = _check_segment("repo", parts[1], spec)
    subdir = _check_subdir(parts[2:], spec)
    return ToolSource(owner=owner, repo=repo, subdir=subdir, ref=ref)


def _from_path_segments(path: str, spec: str, *, allow_tree: bool) -> ToolSource:
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise SpecError(f"Expected owner and repo in {spec!r}")
    owner = _check_segment("owner", parts[0], spec)
    repo = parts[1].removesuffix(".git")
    repo = _check_segment("repo", repo, spec)
    rest = parts[2:]
    if not rest:
        return ToolSource(owner=owner, repo=repo)
    if allow_tree and rest[0] == "tree":
        if len(rest) < 2:
            raise SpecError(f"URL has /tree/ but no ref: {spec!r}")
        ref = rest[1]
        subdir = _check_subdir(rest[2:], spec)
        return ToolSource(owner=owner, repo=repo, subdir=subdir, ref=ref)
    raise SpecError(
        f"Unsupported GitHub URL {spec!r} — use https://github.com/owner/repo"
        f"[/tree/ref[/subdir]] or the owner/repo/subdir@ref short form"
    )
