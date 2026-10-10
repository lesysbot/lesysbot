# LeSysBot tools

Each folder here is a **self-contained tool package**. They ship with LeSysBot
and `lesysbot setup` installs them into `~/.lesysbot/tools/`, so there is nothing
to fetch. To pull a copy newer than your release:

```bash
lesysbot install lesysbot/lesysbot/tools/temperature   # one package
lesysbot install lesysbot/lesysbot/tools               # all of them
```

See [Install tools](../docs/installing-tools.md) and
[Write a tool](../docs/writing-tools.md).

## Catalog

| Package        | Tools                                  | Needs                         |
|----------------|----------------------------------------|-------------------------------|
| `system-info/` | `get_system_info`, `disk_usage`        | —                             |
| `date-time/`   | `get_datetime`                         | —                             |
| `power/`       | `reboot`, `power_off`, `cancel_shutdown` | —                           |
| `temperature/` | `temperature`                          | — (hwmon; `nvidia-smi` for NVIDIA) |
| `network/`     | `dns_lookup`, `ping`, `traceroute`     | `nslookup`, `ping`, `traceroute` |
| `speedtest/`   | `speedtest`                            | —                             |
| `web/`         | `fetch_url`                            | `httpx` (pip)                 |
| `share-dashboard/` | `share_dashboard`, `list_snapshots`, `delete_snapshot` | the [dashboard stack](../docs/dashboards.md) running |

A tool whose required binary isn't on PATH still appears in `/help`, but calling
it returns a one-line explanation instead of failing — so the "Needs" column
above is a guide, not a hard wall.

## Package layout

```
<tool-name>/            # kebab-case folder = the package
  README.md             # frontmatter (name, description, requires) + human docs
  tool.py               # @tool / CLITool definitions  (any non-_ .py is scanned)
  _helpers.py           # OPTIONAL shared helpers (underscore = never scanned)
  requirements.txt      # OPTIONAL pip deps, installed by `lesysbot install`
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
