"""Requirement gating for tools.

LeSysBot runs on Linux only, so a tool never has to ask *which* OS it is on.
What it may still need to declare is which external executables it wants on
PATH (``requires``). ``availability()`` checks them against the current machine
and returns a human-readable reason when a tool can't run here, so the registry
can register an "explaining stub" instead of a tool that would fail cryptically.
"""
from __future__ import annotations

import shutil


def availability(requires: list[str] | None) -> tuple[bool, str | None]:
    """Check whether a tool can run on this machine.

    Returns ``(ok, reason)``. ``ok`` is True when the tool can run here and
    ``reason`` is None; otherwise ``ok`` is False and ``reason`` is a one-line
    explanation suitable for showing to the user.
    """
    for binary in requires or []:
        if shutil.which(binary) is None:
            return False, f"requires '{binary}' on PATH (not found)"

    return True, None
