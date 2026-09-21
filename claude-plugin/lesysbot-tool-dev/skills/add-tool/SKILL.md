---
name: add-tool
description: Scaffold a new LeSysBot tool package following project conventions — a self-contained folder (README + tool.py) using @tool for Python logic or CLITool for shell commands, with confirmation, typing, and requirement gating. Works in any tools repo (standalone, collection, or ~/.lesysbot/tools). Use when asked to "add a tool", "write a tool", "create a command", "make LeSysBot able to <do X>", or expose a new capability/slash command.
---

# Add a LeSysBot tool

LeSysBot tools are **self-contained, copy-paste folder packages** — like a Claude
Skill. A package is a folder with a `README.md` and a `tool.py`. Every
non-`_`-prefixed `.py` inside it is imported by LeSysBot at startup (and
hot-reloaded on save); anything decorated with `@tool` or any `CLITool`
instance is registered and becomes both an LLM-callable function and a
`/slash` command.

## Where the package goes

Pick by the repo you're in:

- **Package-collection repo** (e.g. `lesysbot-packages-official`): each tool
  package is a subdirectory of the repo's `tools/` folder —
  `<repo>/tools/<tool-name>/` (dashboard packages go under `dashboards/`).
  Add a row to the catalog table in the repo's root `README.md` if it has one.
- **Standalone single-tool repo**: the repo root *is* the package —
  `README.md` + `tool.py` at the top level.
- **The core `lesysbot` repo**: packages live under `tools/`; prefer that repo's
  own project skill (`.claude/skills/add-tool/`), which covers core-repo
  extras (catalog row, tests).
- **Local only, no repo**: drop the folder straight into `~/.lesysbot/tools/`
  (or your dev checkout's `tools/`); a running bot hot-reloads it.

Directories named `tests/`, `docs/`, or starting with `.`/`_` are ignored by
the installer, so a collection repo can keep those alongside packages.

## Steps

1. **Create the folder** `<tool-name>/` (kebab-case) with two files:
   `README.md` and `tool.py`. One package may expose several tools.

2. **Pick the form** in `tool.py`:
   - Python logic (parsing, API calls, branching) → `@tool`-decorated `async def` (sync also works; it's wrapped).
   - A single shell command → `CLITool` with a `command` template.

   Use type hints — they become the JSON schema the LLM sees (`str/int/float/bool/list/dict`; anything else → `"string"`). `from __future__ import annotations` is safe; hints resolve via `get_type_hints()`.

   ```python
   # find-files/tool.py
   from lesysbot.mcp import tool, CLITool

   @tool(description="Search files by pattern")
   async def find_files(pattern: str, directory: str = ".") -> str:
       import glob
       return "\n".join(glob.glob(f"{directory}/**/{pattern}", recursive=True))

   df = CLITool(
       name="df",
       description="Show disk usage",
       command="df -h {path}",          # str.format(**kwargs); all params required strings
       params={"path": "Filesystem path"},
   )
   ```

3. **Declare required executables.** LeSysBot targets **Linux only**, so a tool
   never declares an OS — only what it needs on `PATH`:
   - `requires=["nvidia-smi"]` — executables that must be on `PATH`; omit = none.
   Works on `@tool` and `CLITool`. With a missing binary the tool still registers
   but returns a one-line explanation instead of running.
   Pip deps are **not** `requires` (those are PATH binaries) — import them in the
   tool, handle `ImportError` with a friendly message, and list them in the
   package's `requirements.txt` (printed at install time, not auto-installed).

4. **Write `README.md`** with frontmatter mirroring the code (for humans, any
   catalog, and the tools CLI — `lesysbot list/info` display it)
   and a short usage blurb:

   ```markdown
   ---
   name: find-files
   description: Search files by pattern
   requires: []
   version: "1.0.0"        # shown/recorded by `lesysbot install`/`list`; bump on release
   ---
   # find-files
   **Needs:** nothing
   - `/find_files <pattern> [directory]` — recursive glob.
   ```

5. **Guard destructive tools** with `confirm=True` (generic prompt) or `confirm="custom message?"`. Only gates **LLM-initiated** calls; a direct `/tool` call skips it.

6. **Share helpers** in a `_`-prefixed file inside the package (e.g. `find-files/_helpers.py`) — underscore files aren't loaded as tools but are importable (`from _helpers import ...`). The package dir is on `sys.path` **only while the package loads**, so keep such imports at module top level (not lazily inside a function body) — that's also what keeps each package bound to its *own* `_helpers.py`. Edits hot-reload too.

7. **Return a string** (or something `str()`-able) — it's what the user/LLM sees.

## Conventions & gotchas

- **Never write a tool that needs root.** No `sudo`/`runas` calls, no
  `setup-sudoers.sh` — the bot can't type a password, so a privileged tool
  either errors out or forces manual setup before it works. Reach for the
  unprivileged route to the same fact (read `/sys` rather than shelling out as
  root; let logind/polkit handle `shutdown`), and when a capability genuinely
  isn't available without root, say so in the reply instead of elevating. See
  https://github.com/lesysbot/lesysbot/blob/main/docs/writing-tools.md.
- Files starting with `_` are ignored by the loader — helpers only.
- A registered tool appears in `/help` automatically; no registration code needed.
- Match the style of existing packages in the repo you're in (or the bundled
  ones: https://github.com/lesysbot/lesysbot/tree/main/tools).
- The folder shape above is exactly what `lesysbot install owner/repo[/subdir]`
  downloads, so a package pushed to GitHub is installable as-is — see
  https://github.com/lesysbot/lesysbot/blob/main/docs/sharing-tools.md.

## Verify

- `ruff check .` — lint (from the package or repo root).
- Run LeSysBot with its tools dir pointed at your checkout — no config edits
  needed thanks to `LESYSBOT_*` env overrides:

  ```bash
  # collection repo: packages live under tools/ → point at that folder
  LESYSBOT_MCP__TOOLS_DIR="$PWD/tools" lesysbot --provider cli
  # standalone package repo: the parent dir is the tools dir
  LESYSBOT_MCP__TOOLS_DIR="$(dirname "$PWD")" lesysbot --provider cli
  ```

  Alternatively copy the package folder into `~/.lesysbot/tools/`.
- In the CLI, check `/help` (tool listed; gated tools show a "⚠ unavailable
  here" note) and `/<name> <args>` (runs without the LLM). Hot reload picks up
  saves while the bot is running.

Full reference: https://github.com/lesysbot/lesysbot/blob/main/docs/writing-tools.md
and https://github.com/lesysbot/lesysbot/blob/main/docs/sharing-tools.md.
