"""Single-instance lock (lesysbot/core/singleton.py)."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from lesysbot.core import singleton
from lesysbot.core.config import Settings

# Exits 0 if the lock for "testbot" could be acquired, 1 if it's held elsewhere.
CHILD = (
    "import sys; from lesysbot.core.singleton import acquire_instance_lock; "
    "sys.exit(0 if acquire_instance_lock('testbot') else 1)"
)


def _try_from_subprocess(home: str) -> int:
    env = dict(os.environ, LESYSBOT_HOME=home)
    return subprocess.run([sys.executable, "-c", CHILD], env=env).returncode


def test_lock_blocks_second_process(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    assert singleton.acquire_instance_lock("testbot")
    try:
        assert _try_from_subprocess(str(tmp_path)) == 1
    finally:
        singleton.release_instance_lock("testbot")
    # Released → a fresh process acquires it fine.
    assert _try_from_subprocess(str(tmp_path)) == 0


def test_reacquire_same_process_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    assert singleton.acquire_instance_lock("testbot")
    try:
        assert singleton.acquire_instance_lock("testbot")
    finally:
        singleton.release_instance_lock("testbot")


def test_holder_pid_records_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    assert singleton.acquire_instance_lock("testbot")
    try:
        # Windows byte locks are mandatory: a second handle can't read the PID
        # through the lock we hold, so holder_pid returns None there by design
        # (see its docstring and test_is_running below). Elsewhere it names us.
        expected = None if os.name == "nt" else os.getpid()
        assert singleton.holder_pid("testbot") == expected
    finally:
        singleton.release_instance_lock("testbot")


def test_is_running_ignores_a_stale_lock_file(tmp_path, monkeypatch):
    """The status screen asks "is the service up?" — a leftover file with a dead
    PID must answer no, or a crashed service reads as running forever."""
    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path))
    assert singleton.is_running("testbot") is False          # no file at all

    # A live holder in another process → running.
    env = dict(os.environ, LESYSBOT_HOME=str(tmp_path))
    hold = "from lesysbot.core.singleton import acquire_instance_lock as a; a('testbot'); input()"
    child = subprocess.Popen([sys.executable, "-c", hold], env=env, stdin=subprocess.PIPE)
    try:
        # Wait for the child to have taken the lock (it writes its PID first).
        for _ in range(100):
            if singleton.is_running("testbot"):
                break
            time.sleep(0.05)
        assert singleton.is_running("testbot") is True
        # Windows byte locks are mandatory: holder_pid can't read the PID while
        # another process holds the lock (see its docstring), so it returns None
        # there. Only assert the PID off-Windows — the post-exit read below,
        # once the lock is released, works on every platform.
        if os.name != "nt":
            assert singleton.holder_pid("testbot") == child.pid
    finally:
        child.stdin.close()
        child.wait(timeout=10)

    # Process gone, lock file (and its stale PID) left behind → not running.
    assert (tmp_path / "testbot.lock").exists()
    assert singleton.holder_pid("testbot") == child.pid
    assert singleton.is_running("testbot") is False

    # Our own lock counts as running without disturbing it.
    assert singleton.acquire_instance_lock("testbot")
    try:
        assert singleton.is_running("testbot") is True
    finally:
        singleton.release_instance_lock("testbot")


def test_instance_key_separates_bots_by_token():
    a, b, c = Settings(), Settings(), Settings()
    for s in (a, b, c):
        s.messaging.provider = "telegram"
    a.messaging.telegram.token = "111:aaa"
    b.messaging.telegram.token = "111:aaa"
    c.messaging.telegram.token = "222:bbb"
    assert singleton.instance_key(a) == singleton.instance_key(b)
    assert singleton.instance_key(a) != singleton.instance_key(c)
