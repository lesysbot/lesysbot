---
name: share-dashboard
description: Publish the Grafana system dashboard as a public snapshot on snapshots.raintank.io, with a chosen expiration; list and delete your shares
platforms: all
requires: []
version: "1.1.0"
---
# share-dashboard

**Runs on:** Linux · macOS · Windows · **Needs:** the [monitoring stack](../../monitoring/README.md) running (Grafana + Prometheus)

Turn "share me the dashboard" into a link. This publishes a **point-in-time
snapshot** of your System Overview dashboard — the current graphs baked in as
data — to Grafana's public snapshot server, **snapshots.raintank.io**, and lets
you list and delete your shares.

- `/share_dashboard [expiration]` — publish a snapshot and return the public
  link. `expiration` is one of `1h`, `6h`, `12h`, `1d`, `7d`, `30d`, `never`
  (default `1h`). The link works for anyone, until it expires.
- `/list_snapshots` — list the snapshots Grafana currently holds (the same set as
  Grafana's own `/dashboard/snapshots` page), each with its link and time left —
  plus any still‑live shares Grafana has already pruned but the tool still tracks
  (flagged, so you can still delete them).
- `/delete_snapshot <number|key|all>` — delete a share. It's removed from
  Grafana's registry **and** from raintank, so the public copy actually goes away.
  `<number>` comes from `/list_snapshots`.

In chat you don't need the slash commands — just say *"share me the dashboard for
a day"*, *"list my shared dashboards"*, or *"delete the last snapshot"* and the
model calls the right one.

## What gets shared

A snapshot embeds the **last hour** of every panel's data (CPU, memory, disk,
network, temperatures, GPU) as static values baked into each panel, so it renders
on the public server without any access back to your machine or your Prometheus.
It is a **public link** — anyone who has it can view those metrics until it
expires, so pick an expiration you're comfortable with, and delete shares you no
longer need.

## How it works (and two things worth knowing)

The tool pulls your dashboard from Grafana, replays each panel's Prometheus query,
bakes the results into each panel target, and POSTs the model to **Grafana's own**
`/api/snapshots` with `external: true` — Grafana then relays it to raintank.
Publishing *through* Grafana (rather than straight to raintank) is what makes the
snapshot render correctly on Grafana 11, and it's why `/list_snapshots` reads
Grafana's registry as the source of truth.

- **A just‑deleted link may still load for a while.** raintank serves a *cached*
  copy of a deleted snapshot for up to ~1 hour (its own delete response says so),
  so a share you just removed can keep resolving briefly before it clears.
- **Snapshots made outside the bot can't be deleted by the tool.** If you publish
  a snapshot from Grafana's own browser "Publish snapshot" button, the tool never
  sees its secret delete key — and raintank will only delete a snapshot when given
  that key. Grafana also prunes its record of external snapshots quickly, so such
  a share becomes un‑deletable and only clears at its expiry. **Share through the
  bot** (as above) to keep snapshots cleanable.

## Configuration (all optional)

Defaults assume the bundled stack on the same machine. **If you don't set
`LESYSBOT_GRAFANA_URL`, the tool finds Grafana automatically** — it probes the
usual local ports (3000, then 3001) and uses the first that answers as Grafana
(verified via `/api/health`), so a stack bumped to 3001 because 3000 was taken
still works with no config. Set the env vars only to override:

| Variable | Default | Purpose |
|---|---|---|
| `LESYSBOT_GRAFANA_URL` | auto-detect (`localhost:3000`/`3001`) | Grafana base URL |
| `LESYSBOT_GRAFANA_USER` / `LESYSBOT_GRAFANA_PASSWORD` | `admin` / `admin` | basic auth |
| `LESYSBOT_GRAFANA_TOKEN` | — | Bearer token (used instead of user/password) |
| `LESYSBOT_GRAFANA_DS_UID` | `prometheus` | Prometheus datasource uid |
| `LESYSBOT_DASHBOARD_UID` | first dashboard tagged `lesysbot` | which dashboard to share |
| `LESYSBOT_RAINTANK_URL` | `https://snapshots.raintank.io` | snapshot server |

`/list_snapshots` reads Grafana's snapshot registry (`GET /api/dashboard/snapshots`).
`~/.lesysbot/dashboard_snapshots.json` is a local record of the shares you made
through the bot — it keeps each snapshot's raintank delete key so the tool can
still clean up shares Grafana has since pruned, and it serves as a fallback list
when Grafana is unreachable.
