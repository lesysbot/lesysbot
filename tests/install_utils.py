"""Shared helpers for the tool-installer tests — all network-free.

``make_github_zip`` builds zipballs shaped exactly like GitHub's (single
``repo-ref/`` root, commit SHA in the archive comment); ``FakeFetcher`` serves
them from a dict and records every requested URL so tests can assert the
zipball candidate fallback order.
"""

from __future__ import annotations

import io
import zipfile

from lesysbot.install.errors import FetchError

SHA = "0123456789abcdef0123456789abcdef01234567"


def make_github_zip(
    root_name: str, files: dict[str, str], comment_sha: str | None = SHA
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{root_name}/", "")
        for rel, content in files.items():
            zf.writestr(f"{root_name}/{rel}", content)
        if comment_sha:
            zf.comment = comment_sha.encode()
    return buf.getvalue()


class FakeFetcher:
    def __init__(self, responses: dict[str, bytes] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[str] = []

    def get(self, url: str) -> bytes:
        self.requests.append(url)
        if url in self.responses:
            return self.responses[url]
        raise FetchError(404, url)


TOOL_PY = """\
from lesysbot.mcp import tool


@tool(description="Say hello")
async def hello(name: str = "world") -> str:
    return f"hello {name}"
"""

README = """\
---
name: {name}
description: {description}
requires: []
version: "1.2.0"
---
# {name}
"""


def package_files(name: str, description: str = "A test tool") -> dict[str, str]:
    """Files for one tool package, keyed relative to the package dir."""
    return {
        "README.md": README.format(name=name, description=description),
        "tool.py": TOOL_PY,
    }
