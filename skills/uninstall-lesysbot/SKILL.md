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
the virtual environment, and the PATH entry it added to your shell startup files.
**`~/.lesysbot` is kept** unless `--purge`/`-Purge`, so a reinstall finds your
config, tools and logs as you left them.

Installed some other way? Then `pipx uninstall lesysbot` (or delete the venv you
made), remove the service by hand — see [manage-service](../manage-service/SKILL.md) —
and `rm -rf ~/.lesysbot` when done with the data.

<details>
<summary>The older <code>scripts/uninstall.sh</code>, from a clone</summary>

Still present and still works, for installs that predate the current installer.

It undoes everything the installer set up, in order:

1. **Stops and removes the background service** (the `systemd --user` unit) —
   every install has one, since it serves the control panel. It also offers to
   disable `loginctl` linger if the installer enabled it.
2. **Reports leftover sudoers rules** from older versions
   (`/etc/sudoers.d/lesysbot-rtcwake`, `…-shutdown-wake`) and prints the `rm`
   command — it does *not* delete them, which would make uninstall prompt for a
   password. Nothing LeSysBot ships needs root any more, so on a current
   install this step prints nothing.
3. **Uninstalls the `lesysbot` Python package** via pip.
4. **Offers to stop the Grafana dashboard** (the Docker containers
   setup started) when a seeded `~/.lesysbot/dashboard` and `docker` are
   present. It runs `start.sh down` (no `-v`), so the Docker volumes with stored
   history survive a re-install.
5. **Asks before deleting `~/.lesysbot`** (config, tools, dashboard, logs;
   honours `LESYSBOT_HOME`). Default is **No** — keeping it means a later
   re-install finds settings and custom tools exactly as left. Answer `y` only
   for a completely clean machine.

Works for both wizard and manual installs — with no service present, step 1
skips itself.

</details>

## 2. Manual removal (no repo clone available)

**Stop + remove the service:**

```bash
# the systemd --user service
systemctl --user disable --now lesysbot
rm ~/.config/systemd/user/lesysbot.service
systemctl --user daemon-reload
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
