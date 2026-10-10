---
name: add-tool
description: Scaffold a new LeSysBot tool package in tools/ following project conventions — a self-contained folder (README + tool.py) using @tool for Python logic or CLITool for shell commands, with confirmation, typing, and requirement gating. Use when asked to "add a tool", "write a tool", "create a command", "make LeSysBot able to <do X>", or expose a new capability/slash command.
---

# Add a LeSysBot tool

LeSysBot tools are **self-contained, copy-paste folder packages** under `tools/` —
like a Claude Skill. A package is a folder with a `README.md` and a `tool.py`.
Every non-`_`-prefixed `.py` inside it is imported at startup (and hot-reloaded on
save); anything decorated with `@tool` or any `CLITool` instance is registered and
becomes both an LLM-callable function and a `/slash` command. (A loose `.py`
dropped straight in `tools/` also still works for quick local tools.)

## Steps

1. **Create the folder** `tools/<tool-name>/` (kebab-case) with two files:
   `README.md` and `tool.py`. One package may expose several tools.

2. **Pick the form** in `tool.py`:
   - Python logic (parsing, API calls, branching) → `@tool`-decorated `async def` (sync also works; it's wrapped).
   - A single shell command → `CLITool` with a `command` template.

   Use type hints — they become the JSON schema the LLM sees (`str/int/float/bool/list/dict`; anything else → `"string"`). `from __future__ import annotations` is safe; hints resolve via `get_type_hints()`.

   ```python
   # tools/find-files/tool.py
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
   tool, handle `ImportError`, and list them in the package's `requirements.txt`.

4. **Write `README.md`** with frontmatter mirroring the code (for humans, the
   catalog, and the artifact CLI — `lesysbot list/info` display it)
   and a short usage blurb:

   ```markdown
   ---
   name: find-files
   description: Search files by pattern
   requires: []
   version: "1.0.0"        # optional; shown/recorded by `lesysbot list/info`
   ---
   # find-files
   **Needs:** nothing
   - `/find_files <pattern> [directory]` — recursive glob.
   ```

5. **Guard destructive tools** with `confirm=True` (generic prompt) or `confirm="custom message?"`. Only gates **LLM-initiated** calls; a direct `/tool` call skips it.

6. **Share helpers** in a `_`-prefixed file inside the package (e.g. `tools/find-files/_helpers.py`) — underscore files aren't loaded as tools but are importable (`from _helpers import ...`). The package dir is on `sys.path` **only while the package loads**, so keep such imports at module top level (not lazily inside a function body) — that's also what keeps each package bound to its *own* `_helpers.py`. Edits hot-reload too.

7. **Return a string** (or something `str()`-able) — it's what the user/LLM sees.

## Conventions & gotchas

- **Never write a tool that needs root.** No `sudo`/`runas` calls, no
  `setup-sudoers.sh` — the bot can't type a password, so a privileged tool
  either errors out or forces manual setup before it works. Reach for the
  unprivileged route to the same fact (read `/sys` rather than shelling out as
  root; let logind/polkit handle `shutdown`), and when a capability genuinely
  isn't available without root, say so in the reply instead of elevating. See
  [docs/writing-tools.md](../../../docs/writing-tools.md) ("Never require root").
- Files starting with `_` are ignored by the loader — helpers only.
- A new tool appears in `/help` automatically; no registration code needed.
- Match the style of existing packages in `tools/` (e.g. `system-info/`, `speedtest/`).
- Add a row to `tools/README.md` (the catalog table).
- The same folder shape is what `lesysbot install owner/repo` downloads,
  so a package pushed to its own GitHub repo is installable as-is (and the
  bundled ones install via `lesysbot install lesysbot/lesysbot/tools/<name>`)
  — see [docs/writing-tools.md → Share it](../../../docs/writing-tools.md#share-it).

## Verify

- `ruff check tools/` — lint.
- Run `lesysbot --provider cli`, then `/help` (tool listed; gated tools show a "⚠ unavailable here" note) and `/<name> <args>` (runs without the LLM). Hot reload picks up saves.
- If logic is non-trivial, add a test under `tests/` (registries are built over temp tool dirs — see `tests/test_registry.py`; `asyncio_mode=auto` means async tests need no decorator).

Full reference: [docs/writing-tools.md](../../../docs/writing-tools.md), the catalog [tools/README.md](../../../tools/README.md), and the tool-registry/decorator notes in [CLAUDE.md](../../../CLAUDE.md).
