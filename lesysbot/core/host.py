"""Facts about the machine LeSysBot is running on.

This is what is left of the old ``lesysbot/mcp/platform.py`` after the project
went Linux-only. The OS *gating* it existed for is gone — there is no longer an
OS to choose between — but two of its facts outlived it:

* **architecture**, because x86_64 and arm64 Linux boxes genuinely differ (a
  package shipping a prebuilt exporter binary has to say which one it is), and
* **OS version**, because exporter metric names move between distro releases,
  so a dashboard may need "Ubuntu >= 24.04" even though the OS is a given.

``current_os()`` survives as a constant so the marketplace and the dashboard
renderer can keep labelling and filtering without special-casing; it is the one
value here that can no longer vary.
"""
from __future__ import annotations

import platform

#: The only OS LeSysBot supports. Kept as a function (not a bare constant) so
#: callers filtering a manifest's `os:` field read the same either way.
_OS = "linux"

# Spellings of the same machine. A manifest saying `arm64` has to match a Linux
# box reporting `aarch64`, or every Raspberry Pi reads as the wrong hardware.
_ARCH_ALIASES = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}


def current_os() -> str:
    """Always ``"linux"`` — LeSysBot targets Linux only."""
    return _OS


def normalize_arch(name: str) -> str:
    """Fold the common spellings of one architecture onto a single name."""
    name = name.strip().lower()
    return _ARCH_ALIASES.get(name, name)


def current_arch() -> str:
    """This machine's CPU architecture, normalized ('x86_64' | 'arm64' | …)."""
    return normalize_arch(platform.machine())


def os_version() -> str:
    """The distro release from ``/etc/os-release``, or "" when unreadable.

    ``VERSION_ID`` — the distro release, not the kernel. A dashboard branching
    on the OS cares which Ubuntu it is (which exporters and metric names
    exist), and ``platform.release()`` only ever answers the latter.

    Best-effort by design: an unknown version returns "" and every caller must
    treat that as "no constraint can be evaluated" rather than a failure. This
    runs on the status screen, so it never raises and never shells out.
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
