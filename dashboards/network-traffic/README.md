---
name: network-traffic
kind: dashboard
description: Per-interface network throughput (received/sent) over time
version: "1.1.0"
platforms: all
prerequisites:
  - service: prometheus
  - metric: node_network_receive_bytes_total
---
# network-traffic

A Grafana dashboard of **per-interface network throughput** — bytes received
and sent per second, one series per interface, loopback and virtual interfaces
filtered out.

Where [System Overview](../system-overview/README.md) gives network one row
among many, this is the whole page: a longer window and a panel per direction,
for when the question is "what is this link actually doing?" rather than "is
the machine healthy?".

**Needs:** the [dashboard stack](../../dashboard/README.md) running, with
Prometheus scraping node_exporter. If it isn't up yet, the dashboard is
installed but **withheld** with a reason until `lesysbot dashboard start` —
a panel querying a metric nothing collects looks exactly like a broken panel.

## Install

It ships with LeSysBot and is seeded into `~/.lesysbot/` by `lesysbot setup`.
To pull a newer copy than your installed version has:

```bash
lesysbot install lesysbot/lesysbot/dashboards/network-traffic
lesysbot dashboard render     # or it renders automatically on install
```

Grafana picks it up within 30 seconds.
