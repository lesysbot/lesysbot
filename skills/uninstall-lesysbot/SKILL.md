---
name: uninstall-lesysbot
description: Remove LeSysBot from a machine — stop and remove the background service, uninstall the Python package, and optionally delete the ~/.lesysbot data directory — via the uninstall script or fully by hand. Use when asked to "uninstall lesysbot", "remove lesysbot", or "clean lesysbot off this machine".
---

# Uninstall LeSysBot

## 1. The installer's own uninstall (preferred)

The installer leaves a copy of itself in the install directory, so this needs no
network and no clone:

```bash
~/.local/share/lesysbot/install.sh --uninstall            # Linux/macOS
~/.local/share/lesysbot/install.sh --uninstall --purge    # …and delete ~/.lesysbot
```

```powershell
& "$env:USERPROFILE\.local\share\lesysbot\install.ps1" -Uninstall
& "$env:USERPROFILE\.local\share\lesysbot\install.ps1" -Uninstall -Purge
```

It removes only what the installer created: the service, the `lesysbot` command,
the virtual environment, the PATH entry it added to your shell startup files, and
it stops the Grafana dashboard stack (brew services and/or Docker containers,
without deleting the stored history). **`~/.lesysbot` is kept** unless
`--purge`/`-Purge`, so a reinstall finds your config, tools and logs as you left
them.

<details>
<summary><code>scripts/uninstall.sh</code>, for a pip/clone install</summary>

The installer's `--uninstall` only knows about the venv it created, so an install
done by hand (`pip install -e .` from a checkout) needs the repo's own script:

```bash
sh scripts/uninstall.sh          # Linux/macOS
.\scripts\uninstall.ps1          # Windows
```

It walks the same ground interactively: stops and removes the background service
(and offers to disable `loginctl` linger on Linux), removes the program — the
venv and the `lesysbot` command if a one-command install is present, falling back
to `pip uninstall` for one done by hand — offers to stop the dashboard stack, and
**asks before deleting `~/.lesysbot`** (default **No** — keeping it means a later
re-install finds settings and custom tools exactly as left; honours
`LESYSBOT_HOME`). With no service present, that step skips itself.

A `lesysbot` on PATH that points somewhere else (pipx, a distro package, a second
`--prefix` install) is reported and left alone rather than deleted. Every prompt
defaults to **No**, so running this with no terminal attached — a script, a CI
step — removes the program and keeps your data instead of stopping half-way.

Skip the service teardown with `LESYSBOT_SKIP_SERVICE=1`; it lives at a fixed
per-user path that `LESYSBOT_INSTALL_DIR`/`LESYSBOT_BIN_DIR` do not move, so a
sandboxed run needs that guard to leave the real machine's service alone.

</details>

Installed some other way? Then `pipx uninstall lesysbot` (or delete the venv you
made), remove the service by hand — see [manage-service](../manage-service/SKILL.md) —
and `rm -rf ~/.lesysbot` when done with the data.

## 2. Manual removal (no repo clone available)

**Stop + remove the service:**

```bash
# Linux (systemd user service)
systemctl --user disable --now lesysbot
rm ~/.config/systemd/user/lesysbot.service
systemctl --user daemon-reload

# macOS (launchd agent)
launchctl unload -w ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist
rm ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist
```

```powershell
# Windows (Task Scheduler)
Unregister-ScheduledTask -TaskName 'LeSysBot' -Confirm:$false
```

**Uninstall the package, then (optionally) the data:**

```bash
pip uninstall lesysbot
rm -rf ~/.lesysbot          # ONLY if the user confirms losing config + custom tools
```

## Before deleting `~/.lesysbot`

Confirm with the user first — it holds their hand-edited `config.yaml`
(possibly with API keys/tokens they have nowhere else), custom tools in
`tools/`, and logs. If they might reinstall later, keep it.

## Related

- Updating instead of removing: [update-lesysbot](../update-lesysbot/SKILL.md).
- Only stopping the bot, not removing it: [manage-service](../manage-service/SKILL.md).
