# LeSysBot tools

Each folder here is a **self-contained, copy-paste tool package** — like a Claude
Skill. Drop a folder into your `~/.lesysbot/tools/` (the live tools dir for an
installed setup) and restart LeSysBot; the tool auto-registers as both a `/slash`
command and an LLM-callable function. No registration code, no edits elsewhere.

These packages can also be installed straight from this repo, so instead of copying
folders you can install them by name:

```bash
lesysbot tools install lesysbot/lesysbot/tools/gpu-temp
```

See [docs/installing-tools.md](../docs/installing-tools.md).

## Catalog

| Package        | Tools                                  | Runs on            | Needs                         |
|----------------|----------------------------------------|--------------------|-------------------------------|
| `system-info/` | `get_system_info`, `disk_usage`        | Linux/macOS/Win    | —                             |
| `date-time/`   | `get_datetime`                         | Linux/macOS/Win    | —                             |
| `power/`       | `reboot`, `power_off`, `cancel_shutdown` | Linux/macOS/Win  | —                             |
| `cpu-temp/`    | `cpu_temp`                             | Linux              | — (reads `/sys` sensors)      |
| `gpu-temp/`    | `gpu_temp`                             | Linux, Windows     | `nvidia-smi` (NVIDIA driver)  |
| `speedtest/`   | `speedtest`                            | Linux/macOS/Win    | —                             |
| `web/`         | `fetch_url`                            | Linux/macOS/Win    | `httpx` (pip)                 |
| `share-dashboard/` | `share_dashboard`, `list_snapshots`, `delete_snapshot` | Linux/macOS/Win | the [monitoring stack](../monitoring/README.md) running |

A tool whose OS or required binary isn't satisfied still appears in `/help`, but
calling it returns a one-line explanation instead of failing — so the catalog
above is a guide, not a hard wall.

OS-specific packages live in the official per-platform companion repos —
install the one matching your machine:

```bash
lesysbot tools install lesysbot/lesysbot-linux-tools-official     # ping/DNS/traceroute (also macOS), hwmon temps
lesysbot tools install lesysbot/lesysbot-windows-tools-official   # ping/tracert, WMI temps
lesysbot tools install lesysbot/lesysbot-macos-tools-official     # battery, SMC temps
```

## Package layout

```
<tool-name>/            # kebab-case folder = the package
  README.md             # frontmatter (name, description, platforms, requires) + human docs
  tool.py               # @tool / CLITool definitions  (any non-_ .py is scanned)
  _helpers.py           # OPTIONAL shared helpers (underscore = never scanned)
  requirements.txt      # OPTIONAL pip deps, for humans / `pip install -r`
```

Only `README.md` + `tool.py` are required. One package may expose several tools.

## Declaring platform / dependency support

The **decorator args are authoritative** (the loader enforces them); the README
frontmatter mirrors them for humans and this catalog.

```python
from lesysbot.mcp import tool, CLITool

@tool(
    description="Report NVIDIA GPU temperature",
    platforms=["linux", "windows"],   # from {"linux","macos","windows"}; omit = all OSes
    requires=["nvidia-smi"],          # executables that must be on PATH; omit = none
)
async def gpu_temp() -> str: ...

ping = CLITool(
    name="ping", description="Ping a host", command="ping -c 3 {host}",
    params={"host": "Host to ping"}, platforms=["linux", "macos"], requires=["ping"],
)
```

Loose `.py` files dropped directly in `tools/` still work (default: all OSes, no
requirements) — handy for quick local tools. Folders are the shareable form.

See [docs/writing-tools.md](../docs/writing-tools.md) for the full guide.
