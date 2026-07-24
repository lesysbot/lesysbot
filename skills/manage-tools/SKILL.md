---
name: manage-tools
description: Install, list, enable/disable, and remove LeSysBot tools — from GitHub with `lesysbot tools install` or from the terminal — including the trust model, pinning, and updating installed packages. Use when asked to "install a tool", "add the gpu-temp tool", "disable a tool", "remove a tool", "update a tool", or "list my tools".
---

# Manage LeSysBot tools

You can also do all of this from the **control panel** (always on at
`http://127.0.0.1:8700`): a Tools tab lists every tool with enable/disable
toggles, an install box (paste `owner/repo`), and a remove button. It writes the
same state file and tools dir as the CLI below, so the two are interchangeable.

Tools live as folder packages (or loose `.py` files) in the tools dir —
`~/.lesysbot/tools/` for an installed setup. The `lesysbot tools` CLI manages
them, with no running bot needed; it acts on the same state file and directory
the bot loads.

## The CLI

```bash
lesysbot tools install owner/repo   # install package(s) from a GitHub repo
lesysbot tools list                 # every tool: status, source package, origin
lesysbot tools info gpu_temp        # params, platform gating, provenance
lesysbot tools disable gpu_temp     # hide from the LLM; /gpu_temp refuses to run
lesysbot tools enable gpu_temp      # turn it back on
lesysbot tools remove gpu_temp      # DELETE its folder/.py (asks y/N; --yes skips)
```

- **disable/enable** — reversible, persisted to `tool_state.json`. A disabled
  tool is hidden from the LLM's schemas *and* refuses direct `/` calls, but
  stays listed so it can be re-enabled. A running bot applies the change
  **live** — it watches the state file, so a CLI toggle takes effect within a
  second, no restart.
- **remove** — permanent: deletes the whole folder package or loose `.py`,
  **including any sibling tools defined in the same package** (listed before
  the confirm). Installed packages also get their `tools.lock.json` entry
  cleaned. Hot-reload drops it from a running bot immediately. Prefer
  *disable* if the tool might be wanted back.
- `list`/`info` show provenance: `owner/repo@commit7` for installed packages,
  `local` for hand-written ones.

## Installing from GitHub

Installs are **by GitHub link only** — no registry or catalog:

```bash
lesysbot tools install owner/repo                  # whole repo (HEAD)
lesysbot tools install owner/repo@v1.2             # pin branch / tag / 40-hex SHA
lesysbot tools install owner/repo/tools/gpu-temp   # one package in a bigger repo
lesysbot tools install https://github.com/owner/repo
lesysbot tools install owner/repo --only gpu-temp  # cherry-pick from a multi-tool repo
```

Downloads as a zip (no git binary needed), prints the plan — package names,
versions, every file that will land in the tools dir — and asks y/N before
writing. A running bot with hot-reload activates new packages immediately.

- **Trust model:** installed tools are arbitrary Python running as your user,
  no sandbox. Install only from trusted repos (read `tool.py` — they're
  small); prefer pinning `@tag`/`@sha`. The exact commit is recorded in
  `tools.lock.json` either way. `--yes` skips the prompt — scripts only.
- **Pip deps:** a package's `requirements.txt` is **printed**, not run;
  `--install-deps` opts in to running it.
- **Private repos:** set `GITHUB_TOKEN` (or `GH_TOKEN`).
- **Collisions:** the installer refuses to overwrite a folder it didn't
  create (hand-written tools are safe); `--force` overrides.
- **Updating:** re-install a package the lock already owns and it's replaced
  in place — that *is* the update path.
- Bundled packages install by path: `lesysbot tools install lesysbot/lesysbot/tools/gpu-temp`.

What counts as a package in a repo: a root `tool.py` makes the repo itself one
package; otherwise every immediate subdir holding a non-`_` `.py` is one —
looked for under `tools/` first when the repo has that folder, else at the
repo root (`tests/`, `docs/`, dot-/`_`-prefixed dirs skipped).

## Config keys

```yaml
mcp:
  tools_dir: "./tools"          # where packages install & load from
  lock_file: tools.lock.json    # install provenance (repo, pinned commit)
  hot_reload: true
  state_file: tool_state.json   # persisted disabled set
```

All anchor next to the active `config.yaml` (→ `~/.lesysbot/…` when installed),
so `lesysbot tools …` and the bot always resolve the same locations.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Not found: owner/repo@ref` | Check the spec; private repo → set `GITHUB_TOKEN`. |
| `tools dir already has X` | Folder not installed by LeSysBot — `--force` to overwrite. |
| Installed but not in `/help` | Restart the bot if `hot_reload` is off; check `~/.lesysbot/logs/lesysbot.log` for import errors. |
| Tool needs a pip package | Re-run with `--install-deps` or run the printed `pip install -r` line. |
| Tool shows "⚠ unavailable here" | Platform/binary gating — it's registered but this machine can't run it (wrong OS or a `requires` binary missing from PATH). |

## Related

- Write a tool instead of installing one: [write-tool](../write-tool/SKILL.md).
- Calling tools day to day: [use-lesysbot](../use-lesysbot/SKILL.md).
