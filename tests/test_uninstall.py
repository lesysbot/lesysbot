"""Tests for what `scripts/uninstall.sh` actually removes.

These exist because uninstall.sh had drifted behind install.sh. The installer
builds a venv at ``$INSTALL_DIR/venv``, links a shim into ``$BIN_DIR`` and drops
a copy of itself at ``$INSTALL_DIR/install.sh``; the uninstaller knew about none
of it and only ran ``pip uninstall lesysbot`` against the *system* python, which
is where a pre-installer ``pip install`` used to land. Against a venv install
that finds nothing, so "uninstalling" left a fully working ``lesysbot`` on PATH
and the user had no way to tell.

The service is the one thing these must not touch: it lives at a fixed per-user
path that ``LESYSBOT_INSTALL_DIR``/``LESYSBOT_BIN_DIR`` do not move, so every run
here sets ``LESYSBOT_SKIP_SERVICE`` — the same guard install.sh honours. Without
it this suite would tear down the developer's own LaunchAgent.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "uninstall.sh"

# Same exclusion as test_install_macos.py: this drives a bash script that
# Windows never executes, and `bash` is on PATH on the Windows runners so a
# which() guard alone would not fire.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="drives a POSIX shell script; needs bash",
)


def _run(tmp_path: Path, *, shim_target: Path | None) -> subprocess.CompletedProcess:
    """Lay out a fake install under *tmp_path* and uninstall it.

    ``shim_target`` is what ``$BIN_DIR/lesysbot`` points at — the venv's binary
    for a normal install, or somewhere else entirely to stand in for a pipx or
    distro ``lesysbot`` that happens to share the name.
    """
    install_dir = tmp_path / "share" / "lesysbot"
    bin_dir = tmp_path / "bin"
    venv_bin = install_dir / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    bin_dir.mkdir(parents=True)

    (venv_bin / "lesysbot").write_text("#!/bin/sh\nexit 0\n")
    (install_dir / "install.sh").write_text("#!/bin/sh\nexit 0\n")

    target = shim_target if shim_target is not None else venv_bin / "lesysbot"
    (bin_dir / "lesysbot").symlink_to(target)

    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(tmp_path / "home"),
            "LESYSBOT_SKIP_SERVICE": "1",
            "LESYSBOT_INSTALL_DIR": str(install_dir),
            "LESYSBOT_BIN_DIR": str(bin_dir),
            "LESYSBOT_HOME": str(tmp_path / "data"),
        },
    )
    return proc


def test_removes_the_venv_the_shim_and_the_install_dir(tmp_path):
    """The whole point: after this, nothing of the program is left behind."""
    install_dir = tmp_path / "share" / "lesysbot"
    bin_dir = tmp_path / "bin"

    proc = _run(tmp_path, shim_target=None)

    assert proc.returncode == 0, proc.stderr
    assert not (install_dir / "venv").exists(), "the venv survived the uninstall"
    assert not (bin_dir / "lesysbot").exists(), "`lesysbot` is still on PATH"
    assert not (install_dir / "install.sh").exists(), "the installer copy survived"
    assert not install_dir.exists(), "the install directory survived"


def test_leaves_a_shim_that_points_somewhere_else_alone(tmp_path):
    """A `lesysbot` from pipx or a distro package is not ours to delete."""
    other = tmp_path / "other" / "bin" / "lesysbot"
    other.parent.mkdir(parents=True)
    other.write_text("#!/bin/sh\nexit 0\n")

    proc = _run(tmp_path, shim_target=other)

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "bin" / "lesysbot").exists(), "deleted a foreign lesysbot"
    assert "left alone" in proc.stdout
    # Ours still goes, even when the shim is someone else's.
    assert not (tmp_path / "share" / "lesysbot" / "venv").exists()


def test_keeps_the_user_data_home(tmp_path):
    """Config, tools and logs survive unless the (interactive) prompt says so.

    Piped stdin means the y/N prompt reads empty, which is the "no" default —
    an unattended uninstall must never take the user's Telegram token with it.
    """
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.yaml").write_text("messaging:\n  provider: telegram\n")

    proc = _run(tmp_path, shim_target=None)

    assert proc.returncode == 0, proc.stderr
    assert (data / "config.yaml").exists(), "the uninstall ate the user's config"


def test_service_guard_is_honoured(tmp_path):
    """LESYSBOT_SKIP_SERVICE has to work, or this suite uninstalls the dev's own."""
    proc = _run(tmp_path, shim_target=None)

    assert proc.returncode == 0, proc.stderr
    assert "Leaving the background service alone" in proc.stdout
