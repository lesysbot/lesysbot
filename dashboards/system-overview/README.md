---
name: system-overview
kind: dashboard
description: CPU, memory, disk and network for this machine — the default dashboard
version: "2.0.0"
platforms: all
prerequisites:
  - service: prometheus
  - metric: node_cpu_seconds_total
---
# System Overview

The dashboard LeSysBot installs by default, and the only one it installs: an
install has **exactly one** dashboard, and installing another replaces this one.

CPU load and per-core usage, memory and swap, disk space and I/O, and
per-interface network throughput — recorded every 15 seconds and kept for 15
days.

## Why it's deliberately basic

There is no one-size-fits-all dashboard. Operating systems differ, and within
one OS the hardware differs: NVIDIA vs Apple Silicon vs no GPU at all, hwmon vs
the SMC vs WMI thermal zones, NTFS with no inodes. A default that tried to cover
all of it would show blank panels on most machines — and **a blank panel is
indistinguishable from a broken one**, which is the ambiguity this whole design
exists to remove.

So this carries only what a stock `node_exporter` / `windows_exporter` can
always fill. Temperatures, GPU detail and per-filesystem breakdowns are not
here. To get them, install a dashboard built for your machine:

```bash
lesysbot search --kind dashboard
lesysbot install lesysbot/lesysbot-packages-official --only thermals
```

That **replaces** this one. `lesysbot dashboard reset` brings it back.

## Requirements

| | Why |
|---|---|
| Prometheus running | It is the datasource every panel queries |
| `node_cpu_seconds_total` | Proves an exporter is actually being scraped, not just that Prometheus is up |

If either is missing this dashboard is **not provisioned**, and
`lesysbot dashboard current` says why.

## Changing it

Edit `dashboard.py` in this folder and run:

```bash
lesysbot dashboard render
```

Grafana picks the change up within 30 seconds. Adding an NVIDIA row is a few
lines: `build(host, caps, ctx)` already receives the detected capabilities, and
`basic_rows()` is what drops the generator's hardware sections — keep the ones
you want.

A local edit is lost the next time this package is refreshed. To keep changes,
fork the repo and install your fork — then your dashboard *is* the source. See
[the dashboard guide](../../docs/dashboards.md).

The panel definitions live in the stack's `scripts/gen-dashboards.py`, which
stays the single source of truth and is still runnable on its own — it keeps its
temperature and GPU sections for the standalone stack and for richer dashboard
packages to build from. This package is a *selection* from it, never a copy.
