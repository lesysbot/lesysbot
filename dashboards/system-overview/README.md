---
name: system-overview
kind: dashboard
description: CPU, memory, disk, network, temperatures and GPU for this machine
version: "1.0.0"
platforms: all
prerequisites:
  - service: prometheus
  - metric: node_cpu_seconds_total
---
# System Overview

The dashboard LeSysBot installs by default. CPU load and per-core usage, memory
and swap, disk space and I/O, per-interface network throughput, temperatures,
and GPU utilisation — recorded every 15 seconds and kept for 15 days.

**Generated for your machine, not copied.** The panels included depend on what
your hardware can actually report: no NVIDIA row without an NVIDIA driver, no
hwmon temperature rows on a Mac. That is the point — an empty panel should mean
something is broken, never "this OS never had that sensor".

## Requirements

| | Why |
|---|---|
| Prometheus running | It is the datasource every panel queries |
| `node_cpu_seconds_total` | Proves an exporter is actually being scraped, not just that Prometheus is up |

If either is missing, this dashboard is **not provisioned** and `lesysbot list`
says why. A dashboard of blank panels is indistinguishable from a broken one, so
it is withheld rather than shown.

## Customising it

Edit `dashboard.py` in this folder and run:

```bash
lesysbot dashboard render
```

Grafana picks the change up within 30 seconds. Your edit is a file you own, so
it survives `lesysbot update` — unlike editing the dashboard in Grafana's UI,
which is accepted, stored, and then reverted on the next provision.

The panel definitions live in the stack's `scripts/gen-dashboards.py`, which
stays the single source of truth and is still runnable on its own. This package
maps LeSysBot's host and capability vocabulary onto it.
