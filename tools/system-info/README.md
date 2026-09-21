---
name: system-info
description: Basic machine info and free disk space
requires: []
---
# system-info

Pure-Python system inspection — no external dependencies.

**Needs:** nothing

## Tools
- `/get_system_info` — OS, Python version, and CPU architecture.
- `/disk_usage <path>` — total / free / used% for the filesystem at `<path>`.

## Copy-paste
Drop this `system-info/` folder into your `~/.lesysbot/tools/` and restart LeSysBot.
