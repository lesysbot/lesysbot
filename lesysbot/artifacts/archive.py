"""Safe extraction of GitHub zipballs.

GitHub zipballs wrap everything in a single ``repo-ref/`` root directory and
store the full 40-hex commit SHA in the ZIP archive comment — one download
yields both content and an exact pin for the lock file.
"""

from __future__ import annotations

import io
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

from lesysbot.artifacts.errors import ArchiveError

# Zip-bomb guards (module-level so tests can shrink them).
MAX_ENTRIES = 2000
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SKIP_PARTS = ("__pycache__",)


def zip_commit_sha(data: bytes) -> str | None:
    """Commit SHA from the zipball's archive comment, or None if absent."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            comment = zf.comment.decode("ascii", "ignore").strip().lower()
    except zipfile.BadZipFile:
        return None
    return comment if _SHA_RE.match(comment) else None


def _open(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ArchiveError(f"Downloaded archive is not a valid zip: {e}") from e


def zip_root(zf: zipfile.ZipFile) -> str:
    """The single top-level directory all entries share (GitHub guarantees one)."""
    tops = set()
    for name in zf.namelist():
        if name.startswith("/") or "\\" in name:
            raise ArchiveError(f"Archive contains an unsafe path: {name!r}")
        stripped = name.strip("/")
        if stripped:
            tops.add(stripped.split("/", 1)[0])
    if len(tops) != 1:
        raise ArchiveError(
            f"Expected a single top-level directory in the archive, found {sorted(tops)!r}"
        )
    return tops.pop()


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def extract_tree(data: bytes, subdir: str | None, dest: Path) -> None:
    """Extract ``<root>/<subdir>/**`` from the zipball *data* into *dest*.

    Guards against zip-slip paths, symlink entries, and zip bombs; skips
    ``__pycache__`` and ``.git*`` entries.
    """
    with _open(data) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ArchiveError(f"Archive has {len(infos)} entries (max {MAX_ENTRIES})")
        total = sum(i.file_size for i in infos)
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ArchiveError(
                f"Archive expands to {total // 2**20} MiB "
                f"(max {MAX_UNCOMPRESSED_BYTES // 2**20} MiB)"
            )

        root = zip_root(zf)
        prefix = root + "/"
        if subdir:
            prefix += subdir.strip("/") + "/"

        matched = [i for i in infos if i.filename.startswith(prefix)]
        if not matched:
            raise ArchiveError(f"Path '{subdir}' not found in {root}")

        dest.mkdir(parents=True, exist_ok=True)
        dest_resolved = dest.resolve()
        for info in matched:
            rel = info.filename[len(prefix):]
            if not rel:
                continue
            parts = PurePosixPath(rel).parts
            if any(p in ("..",) or p in _SKIP_PARTS or p.startswith(".git") for p in parts):
                if ".." in parts:
                    raise ArchiveError(f"Archive contains an unsafe path: {info.filename!r}")
                continue
            if _is_symlink(info):
                raise ArchiveError(f"Archive contains a symlink entry: {info.filename!r}")
            target = dest.joinpath(*parts)
            if not target.resolve().is_relative_to(dest_resolved):
                raise ArchiveError(f"Archive contains an unsafe path: {info.filename!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
