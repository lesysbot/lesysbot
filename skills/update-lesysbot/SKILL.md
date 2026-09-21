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
bash scripts/install.sh
```

At *"~/.lesysbot/config.yaml already exists — overwrite?"* answer **`n`** to keep
current settings. The wizard reinstalls the package and **stops, replaces, and
restarts** any existing background service, so the new code is live when it
finishes. An existing `~/.lesysbot/tools` is never clobbered.

**Or just reinstall the package** and restart the service yourself:

```bash
pip install ".[all]"              # same extras the install scripts use
# — or, for a development checkout —
pip install -e ".[dev]"

# restart the service so the new code is live:
systemctl --user restart lesysbot
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
lesysbot tools list                        # origin column shows repo@commit
lesysbot tools install owner/repo          # re-fetch HEAD (or @tag to pin)
```

A running bot with hot-reload picks the new files up immediately; otherwise
restart.

## Related

- Full removal instead: [uninstall-lesysbot](../uninstall-lesysbot/SKILL.md).
- Service commands per OS: [manage-service](../manage-service/SKILL.md).
- Something broken after updating: [troubleshoot-lesysbot](../troubleshoot-lesysbot/SKILL.md).
