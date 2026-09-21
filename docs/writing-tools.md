# Write a tool

A tool is the unit of "things LeSysBot can do". Writing one takes about a minute
and doesn't touch any LeSysBot code — you drop a file in a folder and it's live.

---

## Your first tool

Create `~/.lesysbot/tools/hello/tool.py`:

```python
from lesysbot.mcp import tool

@tool(description="Say hello to someone")
async def hello(name: str) -> str:
    return f"Hello, {name}! Nice to meet you."
```

Save it. That's the whole process — no registration, no restart:

```
You: /hello name=World
Bot: Hello, World! Nice to meet you.

You: say hi to Alice for me
Bot: Hello, Alice! Nice to meet you.
```

Both work, because every tool is automatically a `/command` **and** something
the model can choose to call. LeSysBot builds the parameter description the
model sees from your type hints.

> **Where do tools go?** `~/.lesysbot/tools/` for a normal install. Working in a
> source checkout with its own `config.yaml`? Then the repo's `tools/`. The
> `lesysbot` status screen prints the path it's really using.

---

## Wrapping a shell command

If the thing you want already exists as a command, you don't need Python logic:

```python
from lesysbot.mcp import CLITool

ping = CLITool(
    name="ping",
    description="Check if a host is reachable and measure latency",
    command="ping -c 3 {host}",
    params={"host": "Hostname or IP address"},
    timeout=15.0,
)
```

`{host}` is filled in with whatever the model or the user supplies. Every entry
in `params` is required.

**Needs a program that may not be installed?** Name it in `requires` and
LeSysBot marks the tool unavailable rather than letting the shell fail:

```python
mtr = CLITool(
    name="mtr",
    description="Trace the route to a host",
    command="mtr --report --report-cycles 5 {host}",
    params={"host": "Hostname or IP address"},
    requires=["mtr"],
)
```

---

## Asking before doing something drastic

Add `confirm` and LeSysBot won't run the tool until you approve:

```python
@tool(
    description="Delete all log files in a directory",
    confirm="This will permanently delete log files — are you sure?",
)
async def delete_logs(directory: str) -> str:
    import glob, os
    files = glob.glob(f"{directory}/*.log")
    for f in files:
        os.remove(f)
    return f"Deleted {len(files)} log file(s)."
```

`confirm=True` gives a generic prompt; a string gives your own wording. It works
on `CLITool` the same way.

| Where you're chatting | What you see |
|---|---|
| Terminal | The tool name, its arguments, your message, and a `y/n` prompt |
| Telegram | A message with **✅ Yes** / **❌ No** buttons (2-minute timeout) |
| Discord | A message with **✅ Yes** / **❌ No** buttons (5-minute timeout) |

> The prompt only appears when the **model** decides to call the tool. If *you*
> type `/delete_logs …`, it runs — typing it was the decision.

---

## Saying what a tool needs

LeSysBot runs on Linux only, so a tool never declares an OS. What it may declare
is the programs it needs on PATH:

```python
@tool(
    description="Report NVIDIA GPU temperature",
    requires=["nvidia-smi"],          # programs that must be on PATH
)
async def gpu_temp() -> str: ...
```

On a machine that can't satisfy that, the tool still appears in `/help` and the
model still knows about it — but calling it returns an explanation instead of a
confusing error:

```
/gpu_temp
'gpu_temp' is unavailable on this machine — requires 'nvidia-smi' on PATH (not found).
```

> **Upgrading an older tool?** LeSysBot used to gate on OS, so a tool might
> still pass `platforms=[...]` (or give `CLITool` a per-OS `command` dict).
> Both are accepted and ignored, with a one-line warning naming the tool — it
> keeps working, but drop them when you next touch the file.

That's deliberate: the bot can tell you *why* something isn't possible here,
which is more useful than pretending the tool doesn't exist.

> **Python packages are not `requires`.** That list is for programs on your PATH.
> For a pip dependency, import it inside the tool, catch `ImportError`, and
> return a helpful message — then list it in the package's `requirements.txt`.

### Never require root

**Don't write a tool that needs `sudo` or an Administrator prompt.** A tool runs
from a chat message and the bot has no way to type a password, so a privileged
tool either fails outright or forces people through a one-time setup ritual
before it works at all.

In practice: don't shell out through `sudo`, don't ship anything that edits
`/etc/sudoers.d`, and prefer the unprivileged route to the same fact — read
`/sys` instead of running a root-only program, let logind handle `shutdown`
rather than elevating yourself. When something genuinely can't be had without
root, say so in the reply and stop. An honest "this machine doesn't expose that
without root" is a better tool than one that half-works.

---

## Making it shareable

The examples above are a single file, which is perfect for something personal.
To share a tool — or install it from GitHub — give it a folder:

```
gpu-temp/                 # kebab-case folder name
  README.md               # what it does, plus frontmatter
  tool.py                 # your @tool / CLITool definitions
  _helpers.py             # optional; anything starting with _ is never scanned
  requirements.txt        # optional pip dependencies
```

Only `README.md` and `tool.py` are needed. The README's frontmatter describes
the package without anyone having to run its code:

```markdown
---
name: gpu-temp
description: Read NVIDIA GPU temperature
version: 1.0.0
requires: [nvidia-smi]
---
```

The decorator arguments are what LeSysBot actually enforces; the frontmatter
mirrors them for humans and shows up in `lesysbot tools list`.

This is the same shape `lesysbot tools install owner/repo` downloads — push the
folder to a repo and anyone can install it. See
[Share your tools](sharing-tools.md).

---

## Options reference

**`@tool`**

| You want | Write |
|---|---|
| Description from the docstring | omit `description=` |
| A plain sync function | `def` works — it's wrapped automatically |
| An optional parameter | give it a default: `units: str = "metric"` |
| A different tool name | `@tool(name="weather")` |
| Confirmation | `@tool(confirm=True)` or `confirm="your message"` |
| A required program | `@tool(requires=["nvidia-smi"])` |

Type hints map to the schema the model sees: `str` → string, `int` → integer,
`float` → number, `bool` → boolean, `list` → array, `dict` → object. Anything
else is treated as a string.

**`CLITool`**

| Option | Default | What it is |
|---|---|---|
| `name` | — | The tool name, used in `/commands` and by the model. Keep it to lowercase letters, digits and `_` — Telegram and Discord only accept that in a registered slash command, and a tool named otherwise is left out of their command menus (it still works as typed text). |
| `description` | — | What it does |
| `command` | — | Shell command with `{param}` placeholders |
| `params` | `{}` | `param_name → description`; all are required |
| `timeout` | `30.0` | Seconds before the command is killed |
| `confirm` | `False` | `True` or a custom message |
| `requires` | `None` | Programs that must be on PATH |

---

## Under the hood

<details>
<summary><b>Several tools in one file</b></summary>

A file can define as many as you like, mixing both kinds:

```python
from lesysbot.mcp import tool, CLITool
import platform, shutil

@tool
async def get_system_info() -> str:
    """Return basic information about the current machine."""
    return (
        f"OS: {platform.system()} {platform.release()}\n"
        f"Python: {platform.python_version()}\n"
        f"Machine: {platform.machine()}"
    )

@tool(description="Check free disk space at a given path")
async def disk_usage(path: str) -> str:
    usage = shutil.disk_usage(path)
    return (
        f"Path: {path}\n"
        f"Total: {usage.total / 1e9:.1f} GB\n"
        f"Free: {usage.free / 1e9:.1f} GB\n"
        f"Used: {usage.used / usage.total * 100:.1f}%"
    )

df = CLITool(
    name="df",
    description="Show raw disk usage from the df command",
    command="df -h {path}",
    params={"path": "Filesystem path to check"},
)
```

Every non-`_` `.py` file in a package is scanned, not just `tool.py`.

</details>

<details>
<summary><b>Sharing helper code</b></summary>

Anything whose name starts with `_` is skipped by the loader, which makes it the
natural home for helpers:

```python
# gpu-temp/_helpers.py
def format_bytes(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
```

```python
# gpu-temp/tool.py
from _helpers import format_bytes
```

A plain `from _helpers import …` works because each package's own directory is
on the import path while it loads. Two packages can each ship a `_helpers.py`
without colliding — but keep those imports at the top of the module, since the
directory is only on the path during loading. Editing a helper triggers a reload
just like editing the tool.

</details>

<details>
<summary><b>How hot reload works</b></summary>

With `mcp.hot_reload: true` (the default), LeSysBot watches your tools directory
and re-imports everything when any `.py` under it changes:

```
Tool files changed — reloading...
Loaded 3 tool(s) from system.py
```

Cached modules under the tools directory are dropped first, so edits to helpers
take effect too, and which tools you'd disabled survives the reload. Set
`hot_reload: false` if you'd rather restart deliberately.

</details>

<details>
<summary><b>Loose files vs folder packages</b></summary>

Both work, permanently:

- **A loose `.py` in `tools/`** — no metadata, runs on all OSes, requires
  nothing. Best for something quick and personal.
- **A folder package** — README, frontmatter, optional helpers and
  requirements. Best for anything you'll share, install, or come back to.

The folder form is what the installer produces and what the bundled tools use.
Browse them in [`tools/`](../tools/README.md) for real examples.

</details>
