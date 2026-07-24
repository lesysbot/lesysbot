---
name: power
description: Reboot or power off the machine (scheduled 1 minute out, cancellable)
platforms: all
requires: []
---
# power

Power control for the host machine. The right command is chosen per OS
(`shutdown` everywhere; scheduled via logind/polkit on systemd Linux), so it
runs everywhere, as your normal user — no sudo setup, nothing to configure.

Reboot/power-off are **scheduled 1 minute out**, not immediate: an instant
poweroff would kill LeSysBot before its reply reaches you, so a remote
(Telegram/Slack) user would never see whether the command was accepted. The
delay guarantees the acknowledgment arrives — and leaves a window to abort
with `/cancel_shutdown`.

Just before the machine actually goes down (~10 s to spare) LeSysBot pushes a
final "powering off now" / "rebooting now" message, so you're not left
wondering whether the 1-minute countdown really fired. Cancelling the
shutdown also cancels that announcement. (Nothing can be sent *after* power
off — but with the startup notice enabled, a reboot pings you again once the
machine is back.)

**Runs on:** Linux · macOS · Windows  ·  **Needs:** nothing

## Tools (all require confirmation)
- `/reboot` — restart in 1 minute (cancellable).
- `/power_off` — shut down in 1 minute (cancellable).
- `/cancel_shutdown` — cancel a pending shutdown/reboot.

These are destructive and prompt for confirmation when the LLM triggers them.

## Power off with automatic wake-up?

Not supported, on purpose. Waking a machine that's fully off means arming the
motherboard's RTC alarm (`rtcwake`, `pmset`), which needs root — so it only
ever worked after you hand-installed a sudoers rule. LeSysBot no longer ships
tools that require that; to have a machine start itself, use your BIOS/UEFI
"wake on RTC" setting or Wake-on-LAN from another device.

## Copy-paste
Drop this `power/` folder into your `~/.lesysbot/tools/` and restart LeSysBot.
