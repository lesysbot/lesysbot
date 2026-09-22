# Write a tool

A tool is a Python function in a folder. Save the file and it's live — no
restart, no registration.

## Your first tool

Create `~/.lesysbot/tools/hello/tool.py`:

```python
from lesysbot.mcp import tool

@tool(description="Say hello to someone")
async def hello(name: str) -> str:
    return f"Hello, {name}!"
```

Try it:

```
You: /hello Ada
Bot: Hello, Ada!

You: say hi to Ada
Bot: Hello, Ada!
```

Every tool is both a `/command` and something the model can choose. The model
learns the arguments from your type hints.

## Wrap a shell command

```python
from lesysbot.mcp import CLITool

ping = CLITool(
    name="ping",
    description="Check if a host is reachable",
    command="ping -c 3 {host}",
    params={"host": "Hostname or IP address"},
)
```

`{host}` is filled in from the request. Every entry in `params` is required.

## Ask before doing something drastic

```python
@tool(description="Delete old logs", confirm="Delete every .log file in this folder?")
async def delete_logs(directory: str) -> str:
    ...
```

When the model picks this tool, the user must approve first. `confirm=True`
uses a generic question. Typing `/delete_logs …` directly skips the question.

## Say what it needs

```python
@tool(description="Report NVIDIA GPU temperature", requires=["nvidia-smi"])
async def gpu_temp() -> str:
    ...
```

If `nvidia-smi` isn't installed, the tool explains that instead of failing.
`requires` is for programs on your PATH. Put Python packages in a
`requirements.txt` next to `tool.py`.

**Never require root.** A tool runs from a chat message and can't type a
password. Read `/sys` or `/proc` instead of calling `sudo`, and if something
truly needs root, say so in the reply.

## Options

| You want | Write |
|---|---|
| The description from the docstring | leave out `description=` |
| An optional argument | give it a default: `units: str = "metric"` |
| A different name | `@tool(name="weather")` |
| A plain (non-async) function | `def` works too |
| A shell command to time out sooner | `CLITool(..., timeout=10.0)` (default 30) |

Type hints `str`, `int`, `float`, `bool`, `list` and `dict` are understood;
anything else is treated as text. Keep tool names to lowercase letters, digits
and `_` so they appear in the Telegram and Discord menus.

---

## Share it

Give the tool a folder with a `README.md`, push it to GitHub, and anyone can
install it with `lesysbot install you/your-repo`.

```
gpu-temp/
  README.md          what it does, with the frontmatter below
  tool.py            your tools (a file can hold several)
  _helpers.py        optional — files starting with _ aren't scanned
  requirements.txt   optional Python dependencies
```

```markdown
---
name: gpu-temp
description: Read NVIDIA GPU temperature
version: 1.0.0
requires: [nvidia-smi]
---
```

A repo can hold one package at its root, or several in subfolders (or under a
`tools/` folder). Tag releases (`git tag v1.0.0`) so people can pin one with
`@v1.0.0`, and bump `version:` each time.

Before you share, check:

- [ ] Drastic actions use `confirm=`.
- [ ] Every program the tool runs is in `requires=[...]`.
- [ ] It works when installed: `lesysbot install you/repo@your-branch`.

## Let Claude Code write it

The `lesysbot-tool-dev` plugin teaches [Claude Code](https://code.claude.com/docs)
how LeSysBot tools are built. Install it once:

```
/plugin marketplace add lesysbot/lesysbot
/plugin install lesysbot-tool-dev@lesysbot
```

Then ask, for example: *"add a tool that checks whether a systemd unit is
running"*. Update it later with `/plugin marketplace update lesysbot`.

<details>
<summary><b>Offer the plugin to everyone who clones your tools repo</b></summary>

Commit this as `.claude/settings.json`. Claude Code will offer to install the
plugin when someone opens the repo:

```json
{
  "extraKnownMarketplaces": {
    "lesysbot": { "source": { "source": "github", "repo": "lesysbot/lesysbot" } }
  },
  "enabledPlugins": { "lesysbot-tool-dev@lesysbot": true }
}
```

</details>

<details>
<summary><b>Helper files and reloading</b></summary>

Put shared code in a file starting with `_` and import it by name:

```python
# gpu-temp/tool.py
from _helpers import format_bytes
```

Keep those imports at the top of the file. Each package's own folder is on the
import path while it loads, so two packages can each have a `_helpers.py`.

LeSysBot watches the tools folder and reloads when any `.py` file changes.
Turn that off with `mcp.hot_reload: false`.

A loose `.py` file dropped straight into `tools/` works too — handy for a quick
personal tool. Use a folder for anything you'll share.

</details>
