"""Compatibility shims for tool packages written before LeSysBot went Linux-only.

LeSysBot used to gate tools by OS: ``@tool(platforms=[...])`` and a ``CLITool``
whose ``command`` was a dict keyed by OS name. Both are gone — the project
targets Linux only, so there is nothing left to choose between.

Tool packages, though, are installed from GitHub into ``~/.lesysbot/tools`` and
are *not* upgraded with the package. Without these shims an existing package
using the old API raises ``TypeError`` at import and the registry drops it with
only a log line — the tool would silently vanish from a working install. So the
old spellings keep working on this (Linux) host, with a one-time warning naming
the tool so the author can update it.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_warned: set[str] = set()


def _warn_once(what: str, message: str) -> None:
    if what in _warned:
        return
    _warned.add(what)
    logger.warning("%s: %s", what, message)


def note_platforms(tool_name: str, platforms: list[str] | None) -> None:
    """Accept-and-ignore a legacy ``platforms=`` declaration."""
    if platforms is None:
        return
    _warn_once(
        f"tool '{tool_name}'",
        "declares platforms=%r, which LeSysBot no longer uses (Linux only) — "
        "drop the argument. Use requires=[...] for the programs it needs on PATH."
        % (platforms,),
    )


def linux_command(tool_name: str, command: str | dict[str, str]) -> str:
    """Take the Linux entry out of a legacy OS-keyed ``command`` dict.

    Returns ``""`` when the dict has no Linux command at all; ``CLITool._run``
    turns that into a readable error rather than a shell invocation.
    """
    if isinstance(command, str):
        return command
    _warn_once(
        f"tool '{tool_name}'",
        "uses an OS-keyed command dict, which LeSysBot no longer needs "
        "(Linux only) — pass the Linux command as a plain string.",
    )
    return command.get("linux", "")


def linux_requires(
    tool_name: str, requires: list[str] | dict[str, list[str]] | None
) -> list[str] | None:
    """Take the Linux entry out of a legacy OS-keyed ``requires`` dict.

    ``CLITool`` used to accept ``requires`` keyed by OS, for commands that are
    the same tool under different binary names (``traceroute`` vs ``tracert``).
    On Linux only the Linux list can ever apply, and a dict with no Linux key
    means the tool needs nothing here — matching how the old code treated an
    unmentioned OS.
    """
    if requires is None or isinstance(requires, list):
        return requires
    _warn_once(
        f"tool '{tool_name}'",
        "uses an OS-keyed requires dict, which LeSysBot no longer needs "
        "(Linux only) — pass the Linux list as a plain list.",
    )
    return requires.get("linux")
