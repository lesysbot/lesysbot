---
name: write-tool
description: Write a new LeSysBot tool — a self-contained folder package with @tool Python functions or CLITool shell wrappers, confirmation gating, requirement declarations, and helpers — and share it on GitHub so anyone can `lesysbot tools install` it. Use when asked to "add a tool", "write a tool", "make lesysbot able to <do X>", "create a /command", or "publish/share my tool".
---

# Write (and share) a LeSysBot tool

A tool is registered automatically from the tools dir — `~/.lesysbot/tools/` for
an installed setup, the repo's `tools/` for a dev checkout. It becomes **both**
an LLM-callable function and a direct `/slash` command. No registration code,
no edits anywhere else; with `hot_reload: true` (default) a save takes effect
immediately.

## Package layout (the recommended, shareable form)

```
tools/<tool-name>/        # kebab-case folder = the package
  README.md               # frontmatter (name, description, requires) + human docs
  tool.py                 # @tool / CLITool definitions (any non-_ .py is scanned)
  _helpers.py             # OPTIONAL shared helpers (underscore = never scanned as tools)
  requirements.txt        # OPTIONAL pip deps (printed on install, not auto-run)
```

Only `README.md` + `tool.py` are required; one package may expose several
tools. A **loose `.py`** dropped straight in `tools/` also works for quick
local tools.

## Python tool — `@tool`

```python
from lesysbot.mcp import tool

@tool(description="Get the current weather for a city")
async def get_weather(city: str, units: str = "metric") -> str:
    return f"Sunny, 25°C in {city}"
```

The JSON schema the LLM sees is built from the **type hints**:
`str/int/float/bool/list/dict` map to string/integer/number/boolean/array/object;
anything else falls back to `"string"`. Defaults make a parameter optional.
`from __future__ import annotations` is safe (hints resolve via
`get_type_hints()`). Sync `def` works too — it's wrapped in async. Return a
string (or something `str()`-able) — it's what the user/LLM sees.

Options: omit `description=` to use the docstring; `name="…"` overrides the
function name; `confirm=` and `requires=` below.

## Shell tool — `CLITool`

```python
from lesysbot.mcp import CLITool

ping = CLITool(
    name="ping",
    description="Check if a host is reachable and measure latency",
    command="ping -c 3 {host}",          # str.format(**kwargs) interpolation
    params={"host": "Hostname or IP address to ping"},   # ALL params required strings
    timeout=15.0,                        # default 30.0 s, then the command is killed
)
```

Also accepts `confirm=` and `requires=`. Mix `@tool` and `CLITool` freely in
one file.

## Confirmation for destructive tools

```python
@tool(confirm="This will permanently delete log files — are you sure?")
async def delete_logs(directory: str) -> str: ...
```

`confirm=True` gives a generic prompt; a string customizes it. It gates
**LLM-initiated** calls only — a user typing `/delete_logs …` runs immediately
(typing the command *is* the confirmation). CLI asks y/n; Telegram shows
✅/❌ buttons (120 s timeout); Discord shows the same buttons (300 s timeout).

## Requirement gating

LeSysBot targets **Linux only**, so a tool never declares an OS — only the
executables it needs on PATH:

```python
@tool(
    description="Report NVIDIA GPU temperature",
    requires=["nvidia-smi"],          # executables that must be on PATH; omit = none
)
async def gpu_temp() -> str: ...
```

With a missing binary the tool is **still registered** (visible in `/help` and
to the LLM) but calling it returns a one-line explanation instead of running.
Each tool gates independently.

**Pip dependencies are NOT `requires`** (those are PATH binaries). Import the
pip package inside the tool, handle `ImportError` with a friendly message, and
list it in the package's `requirements.txt`.

## Helpers

Files starting with `_` are never loaded as tools but are importable:
`from _helpers import ...`. Each package's own directory is on `sys.path`
**only while the package loads**, so keep helper imports at module top level
(not inside function bodies) — that's also what binds each package to its
*own* `_helpers.py` (two packages can each ship one without clashing).
Helper edits hot-reload too.

## `README.md` frontmatter (mirrors the code, for humans + the tools CLI)

```markdown
---
name: gpu-temp
description: Read NVIDIA GPU temperature
version: "1.0.0"          # optional; shown by `lesysbot tools list/info`
requires: [nvidia-smi]
---
# gpu-temp
**Needs:** nvidia-smi
- `/gpu_temp` — current GPU temperature.
```

The decorator args are what's *enforced*; the frontmatter documents them.

## Verify

1. `ruff check tools/` — lint.
2. `lesysbot --provider cli`, then `/help` (listed? gated tools show
   "⚠ unavailable here") and `/<name> args` — runs without any LLM.
3. Iterate freely: hot reload applies every save (watch
   `logs/lesysbot.log` for "Tool files changed — reloading...").

## Share it on GitHub

Any public repo containing the package shape is installable by anyone —
nothing to register or publish:

```bash
lesysbot tools install you/lesysbot-gpu-temp
```

- **Single-tool repo:** the repo root *is* the package (README.md + tool.py +
  optional `_helpers.py`/`requirements.txt`). The frontmatter `name:`
  overrides the repo name.
- **Multi-tool repo:** one package per subdirectory — under `tools/` when the
  repo has that folder (the official collections' layout), else at the repo
  root; users cherry-pick with `--only NAME` or `you/repo/subdir`. `tests/`,
  `docs/`, dot-/`_`-dirs are ignored.
- **Versioning:** tag releases (`git tag v1.0.0`) so users can pin `@v1.0.0`;
  the installer records the exact commit SHA in their lock file regardless.
  Bump `version:` in the frontmatter with each release.

Checklist before sharing: imports = stdlib + declared `requirements.txt` deps
with `ImportError` handled; destructive actions have `confirm=`; `requires`
declared for every program the tool shells out to; frontmatter filled in;
tested via `lesysbot tools install you/repo@your-branch` or a local copy.

## Related

- Installing/enabling/removing tools: [manage-tools](../manage-tools/SKILL.md).
- Contributing a tool to the bundled catalog (repo `tools/` + catalog table):
  [develop-lesysbot](../develop-lesysbot/SKILL.md).
