# LeSysBot tools

Each folder here is a **self-contained, copy-paste tool package** — like a Claude
Skill. Drop a folder into your `~/.lesysbot/tools/` (the live tools dir for an
installed setup) and restart LeSysBot; the tool auto-registers as both a `/slash`
command and an LLM-callable function. No registration code, no edits elsewhere.

These packages can also be installed straight from this repo, so instead of copying
folders you can install them by name:

```bash
lesysbot tools install lesysbot/lesysbot/tools/temperature
```

See [docs/installing-tools.md](../docs/installing-tools.md).

## Catalog

| Package        | Tools                                  | Needs                         |
|----------------|----------------------------------------|-------------------------------|
| `system-info/` | `get_system_info`, `disk_usage`        | —                             |
| `date-time/`   | `get_datetime`                         | —                             |
| `power/`       | `reboot`, `power_off`, `cancel_shutdown` | —                           |
| `temperature/` | `temperature`                          | — (`nvidia-smi` used if present) |
| `network/`     | `ping`, `dns_lookup`, `traceroute`     | `ping`, `nslookup`, `traceroute` |
| `speedtest/`   | `speedtest`                            | —                             |
| `web/`         | `fetch_url`                            | `httpx` (pip)                 |
| `share-dashboard/` | `share_dashboard`, `list_snapshots`, `delete_snapshot` | the [monitoring stack](../monitoring/README.md) running |

A tool whose required binary isn't on PATH still appears in `/help`, but calling
it returns a one-line explanation instead of failing — so the "Needs" column
above is a guide, not a hard wall. `network/` gates **per tool**: a box without
`traceroute` still gets working `ping` and `dns_lookup`.

## Package layout

```
<tool-name>/            # kebab-case folder = the package
  README.md             # frontmatter (name, description, requires) + human docs
  tool.py               # @tool / CLITool definitions  (any non-_ .py is scanned)
  _helpers.py           # OPTIONAL shared helpers (underscore = never scanned)
  requirements.txt      # OPTIONAL pip deps, for humans / `pip install -r`
```

Only `README.md` + `tool.py` are required. One package may expose several tools.

## Declaring dependencies

LeSysBot targets **Linux only**, so a tool never declares an OS. What it may
declare is the executables it needs on PATH. The **decorator arg is
authoritative** (the loader enforces it); the README frontmatter mirrors it for
humans and this catalog.

```python
from lesysbot.mcp import tool, CLITool

@tool(
    description="Report disk temperatures",
    requires=["smartctl"],            # executables that must be on PATH; omit = none
)
async def disk_temp() -> str: ...

traceroute = CLITool(
    name="traceroute", description="Trace the path to a host",
    command="traceroute -m 15 {host}",
    params={"host": "Host to trace"}, requires=["traceroute"],
)
```

Loose `.py` files dropped directly in `tools/` still work (no requirements by
default) — handy for quick local tools. Folders are the shareable form.

See [docs/writing-tools.md](../docs/writing-tools.md) for the full guide.
