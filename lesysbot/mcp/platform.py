"""Cross-platform gating for tools.

A tool may declare which OSes it runs on (``platforms``) and which external
executables it needs on PATH (``requires``). ``availability()`` checks both
against the current machine and returns a human-readable reason when a tool can't
run here, so the registry can register an "explaining stub" instead of a tool that
would fail cryptically.
"""
from __future__ import annotations

import platform
import shutil

# platform.system() → our short OS names.
_OS_NAMES = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}

# Pretty labels for messages.
_OS_LABELS = {"linux": "Linux", "macos": "macOS", "windows": "Windows"}

# Spellings of the same machine. A manifest saying `arm64` has to match a Linux
# box reporting `aarch64`, or every Raspberry Pi reads as the wrong hardware.
_ARCH_ALIASES = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}


def current_os() -> str:
    """Return the current OS as one of 'linux' | 'macos' | 'windows'.

    Falls back to a lower-cased platform.system() for anything else (e.g. BSD).
    """
    return _OS_NAMES.get(platform.system(), platform.system().lower())


def normalize_arch(name: str) -> str:
    """Fold the common spellings of one architecture onto a single name."""
    name = name.strip().lower()
    return _ARCH_ALIASES.get(name, name)


def current_arch() -> str:
    """This machine's CPU architecture, normalized ('x86_64' | 'arm64' | …)."""
    return normalize_arch(platform.machine())


def os_version() -> str:
    """This machine's OS version, or "" when it can't be determined.

    Deliberately the *marketing* version people recognise and pin against —
    macOS ``14.5`` rather than the Darwin kernel's ``23.5.0``, Windows ``10``
    rather than an NT build number — because that is what a package author
    writes in a manifest and what a user reads back in an error.

    Best-effort by design: an unknown version returns "" and every caller must
    treat that as "no constraint can be evaluated" rather than a failure. This
    runs on the status screen, so it never raises and never shells out.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            return platform.mac_ver()[0]
        if system == "Windows":
            return platform.win32_ver()[0]
        if system == "Linux":
            return _linux_version_id()
    except OSError:
        return ""
    return ""


def _linux_version_id() -> str:
    """``VERSION_ID`` from /etc/os-release — the distro release, not the kernel.

    A dashboard branching on Linux cares which Ubuntu it is (which exporters and
    metric names exist), not which kernel — and ``platform.release()`` only ever
    answers the latter.
    """
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return ""
    for line in lines:
        key, _, value = line.partition("=")
        if key.strip() == "VERSION_ID":
            return value.strip().strip('"').strip("'")
    return ""


def _label(os_name: str) -> str:
    return _OS_LABELS.get(os_name, os_name)


def availability(
    platforms: list[str] | None,
    requires: list[str] | None,
) -> tuple[bool, str | None]:
    """Check whether a tool can run on this machine.

    Returns ``(ok, reason)``. ``ok`` is True when the tool can run here and
    ``reason`` is None; otherwise ``ok`` is False and ``reason`` is a one-line
    explanation suitable for showing to the user.
    """
    if platforms:
        wanted = [p.lower() for p in platforms]
        here = current_os()
        if here not in wanted:
            runs_on = ", ".join(_label(p) for p in wanted)
            return False, f"not supported on {_label(here)} (runs on: {runs_on})"

    for binary in requires or []:
        if shutil.which(binary) is None:
            return False, f"requires '{binary}' on PATH (not found)"

    return True, None
