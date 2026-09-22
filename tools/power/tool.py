"""Power tools — reboot, power off, or cancel a pending shutdown.

These are destructive, so every action sets ``confirm=`` and the agent must get
approval through the adapter before the command runs. The commands deliberately
stay unprivileged: ``shutdown`` schedules through logind under the same polkit
rules as ``systemctl poweroff``, which a local session may invoke without sudo.
Nothing here shells out through ``sudo`` — see ``docs/writing-tools.md`` ("Never require root").

Reboot/power-off are **scheduled 1 minute out** rather than run immediately:
an instant poweroff kills this process before the reply can reach the user, so
a remote (Telegram/Discord) user never learns whether the command was accepted.
The delay guarantees the acknowledgment arrives and leaves a window for
``cancel_shutdown`` to abort.

Just before the scheduled time (~10 s to spare — nothing can send once the
machine is down) a final heads-up is pushed to the requesting user via
``notify_later``, so they see the shutdown actually happening rather than only
the "in 1 minute" acknowledgment. ``cancel_shutdown`` also cancels that
pending announcement.

There is deliberately no "power off, then wake up later" counterpart: arming
an RTC wake alarm needs root, and a tool the user must hand-configure a sudoers
rule for isn't one they can just install and use.
"""
from __future__ import annotations

import asyncio

from lesysbot.mcp import notify_later, tool

# shutdown fires 60 s after scheduling; announce shortly before, leaving
# enough margin for the message to actually get out.
_ANNOUNCE_AFTER = 50.0

_pending_announce: asyncio.Task | None = None


def _announce_later(text: str) -> None:
    """Schedule the just-before-shutdown heads-up, replacing any pending one."""
    global _pending_announce
    _cancel_announce()
    _pending_announce = notify_later(text, _ANNOUNCE_AFTER)


def _cancel_announce() -> None:
    global _pending_announce
    if _pending_announce is not None and not _pending_announce.done():
        _pending_announce.cancel()
    _pending_announce = None


async def _run(cmd: list[str], timeout: float = 15.0) -> tuple[int, str]:
    """Run a command, returning (returncode, combined stdout+stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        # A non-systemd shutdown(8) may stay in the foreground while it waits
        # for the scheduled time; don't hang the agent with it — treat as
        # accepted.
        return 0, "(command still running — scheduled shutdown assumed accepted)"
    return proc.returncode, stdout.decode(errors="replace").strip()


# "+1" (minutes) is the smallest non-immediate delay shutdown accepts; on
# systemd distros this schedules via logind, elsewhere shutdown handles it.
_POWER_CMDS = {
    "reboot": ["shutdown", "-r", "+1"],
    "poweroff": ["shutdown", "-h", "+1"],
    "cancel": ["shutdown", "-c"],
}


def _power_cmd(action: str) -> list[str]:
    """The command for 'reboot' | 'poweroff' | 'cancel'."""
    return _POWER_CMDS[action]


@tool(
    description="Reboot (restart) this machine in 1 minute (cancellable)",
    confirm="⚠️ This will REBOOT the machine in 1 minute. Proceed?",
)
async def reboot() -> str:
    """Schedule a reboot 1 minute from now."""
    code, out = await _run(_power_cmd("reboot"))
    if code == 0:
        _announce_later("🔄 Rebooting now — I'll message again once I'm back online.")
        return (
            "✅ Reboot scheduled — the machine will restart in 1 minute. "
            "I'll send a final message just before it goes down. "
            "Use /cancel_shutdown to abort."
        )
    return f"Reboot failed (exit {code}): {out or 'unknown error — may need elevated privileges.'}"


@tool(
    description="Power off (shut down) this machine in 1 minute (cancellable)",
    confirm="⚠️ This will POWER OFF the machine in 1 minute. Proceed?",
)
async def power_off() -> str:
    """Schedule a power-off 1 minute from now."""
    code, out = await _run(_power_cmd("poweroff"))
    if code == 0:
        _announce_later(
            "⏻ Powering off now — this is my last message until the machine is started again. Goodbye!"
        )
        return (
            "✅ Shutdown scheduled — the machine will power off in 1 minute. "
            "I'll send a final message just before it goes down. "
            "Use /cancel_shutdown to abort."
        )
    return f"Power-off failed (exit {code}): {out or 'unknown error — may need elevated privileges.'}"


@tool(
    description="Cancel a pending/scheduled shutdown or reboot",
    confirm="Cancel the pending shutdown/reboot?",
)
async def cancel_shutdown() -> str:
    """Cancel a scheduled shutdown/reboot."""
    code, out = await _run(_power_cmd("cancel"))
    if code != 0:
        return f"Cancel failed (exit {code}): {out or 'no shutdown was pending, or it needs elevated privileges.'}"
    _cancel_announce()
    return "Cancelled any pending shutdown/reboot."
