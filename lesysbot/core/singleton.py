from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, IO

from lesysbot.core.paths import user_dir

if TYPE_CHECKING:
    from lesysbot.core.config import Settings

# Open lock files kept referenced for the life of the process — closing (or
# garbage-collecting) the handle would release the OS lock.
_held: dict[str, IO[bytes]] = {}


def instance_key(settings: Settings) -> str:
    """Lock key for this bot: provider plus a short digest of its token.

    Keyed on the token so two *different* bots (different tokens) can coexist
    on one machine, while a second copy of the *same* bot — which would fight
    over the same updates — cannot.
    """
    provider = settings.messaging.provider
    if provider == "telegram":
        token = settings.messaging.telegram.token
    elif provider == "discord":
        token = settings.messaging.discord.token
    else:
        token = ""
    digest = hashlib.sha256(token.encode()).hexdigest()[:8] if token else "default"
    return f"lesysbot.{provider}.{digest}"


def _lock_path(key: str) -> Path:
    return user_dir() / f"{key}.lock"


def acquire_instance_lock(key: str) -> bool:
    """Try to become the single running instance for *key*.

    Backed by an OS-level advisory lock on ``~/.lesysbot/<key>.lock``. The
    kernel releases the lock when the holding process exits — crash included —
    so a leftover lock file never wedges a restart. Returns False when another
    live process already holds the lock.
    """
    if key in _held:
        return True
    path = _lock_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    # Record our PID so the "already running" error can name the holder.
    os.ftruncate(fh.fileno(), 0)
    fh.seek(0)
    fh.write(str(os.getpid()).encode("ascii"))
    fh.flush()
    _held[key] = fh
    return True


def release_instance_lock(key: str) -> None:
    """Release a lock this process holds (mainly for tests)."""
    fh = _held.pop(key, None)
    if fh is not None:
        fh.close()


def is_running(key: str) -> bool:
    """True when a live process holds *key*'s lock.

    Not the same as "the lock file exists": the kernel drops the lock when the
    holder exits, but the file (with its now-stale PID) stays behind — so the
    status screen has to test the lock itself, or it reports a crashed service
    as running. Probing takes the lock on a *separate* open file description and
    releases it again, which never disturbs the real holder.
    """
    if key in _held:
        return True
    path = _lock_path(key)
    if not path.exists():
        return False
    try:
        fh = open(path, "a+b")
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        fh.close()


def holder_pid(key: str) -> int | None:
    """PID recorded in the lock file, best effort.

    Returns None when the file is missing or hasn't been written yet, so the
    caller can word its message without a PID.
    """
    try:
        text = _lock_path(key).read_text(encoding="ascii").strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None
