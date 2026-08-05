---
name: update-lesysbot
description: Update LeSysBot to a newer version — pull the latest code, reinstall the package, restart the background service, and update installed tool packages — without losing config or custom tools. Use when asked to "update lesysbot", "upgrade lesysbot", "reinstall lesysbot", or "uninstall and update".
---

# Update LeSysBot

An update never requires touching `~/.lesysbot/config.yaml` or `~/.lesysbot/tools/`
— settings and custom tools are decoupled from the source checkout and survive
every path below.

## 1. Update the code

```bash
cd /path/to/lesysbot        # the original git clone
git pull
```

(If the clone is gone, `git clone https://github.com/lesysbot/lesysbot.git` fresh —
nothing in `~/.lesysbot` depends on the old checkout.)

## 2. Reinstall — pick one

**Re-run the wizard** (simplest; handles the service for you):

```bash
pipx install --force git+https://github.com/lesysbot/lesysbot && lesysbot setup
```

At *"~/.lesysbot/config.yaml already exists — overwrite?"* answer **`n`** to keep
current settings. The wizard reinstalls the package and **stops, replaces, and
restarts** any existing background service, so the new code is live when it
finishes. An existing `~/.lesysbot/tools` is never clobbered.

`~/.lesysbot/dashboard` **is** brought up to date, because that is how a fix to
the stack reaches an existing install: shipped files (scripts, dashboards,
compose, Grafana provisioning) are refreshed when they differ, while `.env`
(ports, Grafana login) and `prometheus/` (hand-added scrape targets) are seeded
once and then never touched. Run the installer from a checkout (`--repo`) for
that; a bare `lesysbot setup` has no source to copy from. Re-run the OS's start
script afterwards (`dashboard/scripts/install-macos.sh` on macOS, `start.sh` on
Linux) so the dashboard is regenerated with the new code.

**Or just reinstall the package** and restart the service yourself:

```bash
pip install ".[all]"              # same extras the install scripts use
# — or, for a development checkout —
pip install -e ".[dev]"

# restart the service (Telegram/Discord installs only):
systemctl --user restart lesysbot                          # Linux
launchctl kickstart -k gui/$(id -u)/com.lesysbot.lesysbot    # macOS
```

```powershell
Stop-ScheduledTask -TaskName LeSysBot; Start-ScheduledTask -TaskName LeSysBot  # Windows
```

CLI-only setups need no restart — the next `lesysbot` launch uses the new code.

## 3. Verify — the stale-install trap

A **non-editable** install in site-packages can shadow a development clone: the
`lesysbot` command silently keeps running the *old* copy, so new flags,
subcommands, or tools "don't exist". After updating, check (from **outside**
the repo directory):

```bash
python -c "import lesysbot; print(lesysbot.__file__)"
```

- Regular users: any site-packages path is fine — just confirm
  `lesysbot --help` shows what the new version should have.
- Developers: the path must point inside the clone; if not, `pip install -e .`.

## 4. Update installed tool packages

Tool packages installed from GitHub are updated by re-installing — a package
already owned by the lock file (`tools.lock.json`) is replaced in place:

```bash
lesysbot list                        # origin column shows repo@commit
lesysbot install owner/repo          # re-fetch HEAD (or @tag to pin)
```

A running bot with hot-reload picks the new files up immediately; otherwise
restart.

## Related

- Full removal instead: [uninstall-lesysbot](../uninstall-lesysbot/SKILL.md).
- Service commands per OS: [manage-service](../manage-service/SKILL.md).
- Something broken after updating: [troubleshoot-lesysbot](../troubleshoot-lesysbot/SKILL.md).
