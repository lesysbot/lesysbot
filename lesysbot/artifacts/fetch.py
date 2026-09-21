"""HTTP layer for tool installs — GitHub zipball downloads via stdlib urllib.

No GitHub *API* calls are made: content comes from codeload zipballs (which are
not API-rate-limited) and the pinned commit SHA is read from the ZIP archive
comment (see :func:`lesysbot.artifacts.archive.zip_commit_sha`).
"""

from __future__ import annotations

import logging
import os
import re
import urllib.error
import urllib.request
from typing import Protocol

from lesysbot import __version__
from lesysbot.artifacts.errors import FetchError
from lesysbot.artifacts.spec import ToolSource

logger = logging.getLogger(__name__)

# Hard cap on a single download; a tool package should be tiny.
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024

_FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class Fetcher(Protocol):
    def get(self, url: str) -> bytes:
        """Return the body at *url*, raising :class:`FetchError` on failure."""
        ...


class UrllibFetcher:
    """Stdlib fetcher. Honors ``GITHUB_TOKEN``/``GH_TOKEN`` for private repos."""

    def __init__(self, timeout: float = 30.0, token: str | None = None) -> None:
        self._timeout = timeout
        self._token = (
            token
            if token is not None
            else os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        )

    def get(self, url: str) -> bytes:
        headers = {"User-Agent": f"lesysbot/{__version__}"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                chunks: list[bytes] = []
                total = 0
                while chunk := resp.read(64 * 1024):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise FetchError(
                            0, url, f"Download exceeds {MAX_DOWNLOAD_BYTES // 2**20} MiB cap"
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
        except urllib.error.HTTPError as e:
            raise FetchError(e.code, url, f"HTTP {e.code} ({e.reason}) for {url}") from e
        except urllib.error.URLError as e:
            raise FetchError(0, url, f"Network error for {url}: {e.reason}") from e


def zipball_candidates(src: ToolSource) -> list[str]:
    """Zipball URLs to try in order for *src*.

    Tags are tried before branches so a tag and branch sharing a name resolve
    with release semantics. The final ``github.com/…/archive`` form follows
    repo-rename redirects that codeload may not.
    """
    base = f"https://codeload.github.com/{src.owner}/{src.repo}/zip"
    archive = f"https://github.com/{src.owner}/{src.repo}/archive"
    ref = src.ref
    if not ref:
        return [f"{base}/HEAD", f"{archive}/HEAD.zip"]
    if _FULL_SHA_RE.match(ref):
        return [f"{base}/{ref}", f"{archive}/{ref}.zip"]
    return [
        f"{base}/refs/tags/{ref}",
        f"{base}/refs/heads/{ref}",
        f"{base}/{ref}",
        f"{archive}/{ref}.zip",
    ]


def download_zipball(fetcher: Fetcher, src: ToolSource) -> bytes:
    """Download the zipball for *src*, walking the candidate URLs on 404."""
    last: FetchError | None = None
    for url in zipball_candidates(src):
        try:
            logger.debug("Trying %s", url)
            return fetcher.get(url)
        except FetchError as e:
            if e.status != 404:
                raise
            last = e
    ref = f"@{src.ref}" if src.ref else ""
    raise FetchError(
        404,
        last.url if last else "",
        f"Not found: {src.slug}{ref} — check the owner/repo and ref. "
        "Private repos need GITHUB_TOKEN (or GH_TOKEN) set.",
    )
