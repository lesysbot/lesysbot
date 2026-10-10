---
name: gpu-detail
kind: dashboard
description: NVIDIA GPU utilization, memory, temperature, and power draw
version: "1.1.0"
platforms: all
prerequisites:
  - gpu: nvidia
  - metric: nvidia_smi_utilization_gpu_ratio
---
# gpu-detail

A Grafana dashboard of **NVIDIA GPU detail**: utilization, memory in use, die
temperature, and power draw, fed by `nvidia_gpu_exporter` through the LeSysBot
dashboard stack.

This package is the working example of the **withholding rule**: a panel
querying a metric nothing collects looks exactly like a broken panel, so on a
machine where `nvidia_smi_utilization_gpu_ratio` isn't being scraped the
dashboard is *not provisioned* — `lesysbot dashboard list` names the reason,
and it appears automatically once the exporter is running. On a machine with
no NVIDIA card that is the permanent state, and costs nothing.

**Needs:** an NVIDIA GPU with driver, and the stack's NVIDIA exporter scraping
(`lesysbot doctor` shows what's missing and the fix).

## Install

It ships with LeSysBot and is seeded into `~/.lesysbot/` by `lesysbot setup`.
To pull a newer copy than your installed version has:

```bash
lesysbot install lesysbot/lesysbot/dashboards/gpu-detail
lesysbot dashboard render     # or it renders automatically on install
```

Grafana picks it up within 30 seconds.
