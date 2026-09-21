---
name: monitor-system
description: Run LeSysBot's default Prometheus + Grafana "System Overview" stack that records CPU, memory, disk, network (Ethernet/Wifi), temperatures (CPU/disk/GPU/sensors) and NVIDIA GPU as time series on a ready-made Grafana dashboard. Linux, localhost-only, no sudo. Use when asked to "monitor my system", "see CPU/GPU/temperature graphs", "set up Grafana/Prometheus", "system dashboard", or "record hardware metrics over time".
---

# System Overview — Prometheus + Grafana

LeSysBot ships a **standard, self-contained monitoring stack** in the
`monitoring/` folder of the repo. It records the machine's **CPU, memory, disk,
network (per interface — Ethernet & Wifi), temperatures and GPU** as Prometheus
time series and shows them on a pre-built Grafana dashboard.

`lesysbot setup` (run by the installer) seeds this stack into
`~/.lesysbot/monitoring` and gets the user to a Grafana dashboard at
**http://localhost:3000** — the mechanism is OS-specific:
If Docker is running, setup *asks* whether to auto-start the bundled stack now
or leave it for manual start; otherwise it prints the no-sudo steps to get
Docker ready (or the link to install Grafana natively instead).

Use the steps below to start/stop the Docker stack by hand, seed it on a box
where Docker arrived later, or reconfigure it. `LESYSBOT_SKIP_MONITORING=1`
before setup skips the step entirely.

Key properties to know before you start:

- **Separate from the bot.** This stack runs as its own containers; LeSysBot's
  only listener is its localhost control panel (port 8700). Everything it
  exposes binds to **`127.0.0.1` only** (nothing on the LAN) and needs **no
  sudo**.
- **Standard components only** — Prometheus, Grafana, `node_exporter`,
  `nvidia_gpu_exporter`. Nothing custom to trust.
- **The only prerequisite is Docker** (Compose v2). Prometheus, Grafana and the
  exporters download and configure themselves on first start.

## Prerequisite: Docker

```bash
docker compose version      # need "v2.x"; if missing, install Docker first
```

Install if absent: [Docker Engine](https://docs.docker.com/engine/install/)
for the distro, then `sudo usermod -aG docker $USER` and re-login.

**Get the files.** The stack lives in the repo's `monitoring/` folder. If the
user installed LeSysBot with `pip` (no checkout), fetch it first:

```bash
git clone https://github.com/lesysbot/lesysbot && cd lesysbot/monitoring
```

Run every command below from that `monitoring/` folder. It is self-contained —
copying just that folder is enough.

## Start it (one command per OS)

Run from the repo's `monitoring/` folder.

| Start | Stop |
|---|---|
| `./scripts/start.sh` | `./scripts/start.sh down` |

`start.sh` auto-detects the NVIDIA GPU and does the right thing. Then open
**http://localhost:3000** (login `admin` / `admin`). The dashboard is in the
**LeSysBot** folder in Grafana.

**What the start scripts do under the hood** (useful when debugging):

- Runs Prometheus + Grafana + `node-exporter` all on the **host network**,
  bound to localhost (`docker compose up -d`). Host networking is required so
  `node_exporter` sees the real NICs and to
  avoid the `ufw`/firewall block on container→host traffic. **GPU is automatic:**
  `start.sh` adds `--profile gpu` (containerised exporter) when the Docker NVIDIA
  runtime is present, else falls back to a native GPU exporter
  (`run-exporters.sh`) — no nvidia-container-toolkit required either way; no GPU
  → skipped.
## What you get

**One dashboard** — **System Overview**, fed by `node_exporter` plus
`nvidia_gpu_exporter`. It covers: **CPU** (busy %, per-mode, load, cores) ·
**Memory** (used/cached, swap) · **Disk** (used % per mount, read/write) ·
**Network** per interface (the interface name distinguishes Ethernet from Wifi) ·
**Temperatures** · **GPU** (NVIDIA: util, memory, temp, power).

### Temperature sensor coverage

Only what the kernel exposes without sudo is shown:

| Sensor | Source |
|---|---|
| **CPU** (package + cores) | `hwmon` — `coretemp` / `k10temp` |
| **Disk** (NVMe/SATA) | `hwmon` — `nvme` / `drivetemp` |
| **ACPI / chipset / Wifi radio** | `thermal_zone` |
| **GPU** (NVIDIA) | `nvidia_gpu_exporter` |

A SATA drive temp may need `sudo modprobe drivetemp` once; NVMe needs nothing.
Panels for sensors the hardware lacks stay empty.

## Ports, credentials, configuration

Everything binds to loopback. Grafana `127.0.0.1:3000`, Prometheus
`127.0.0.1:9090` (`/targets` shows exporter health), exporters on
`:9100`/`:9835`.

- **Login:** `admin` / `admin`. **Change it** before exposing Grafana anywhere.
- **Override defaults:** copy `monitoring/.env.example` → `monitoring/.env`
  (git-ignored) and set `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_PORT`, `PROM_PORT`,
  `PROM_RETENTION` (how long history is kept). `GRAFANA_ADMIN_PASSWORD` only
  applies on the **first** Grafana start; to change it later use the Grafana UI
  or `docker exec lesysbot-grafana grafana cli admin reset-admin-password NEW`.
- **Add another host/exporter:** add its `host:port` to the right job in
  `prometheus/prometheus.yml`, then `curl -X POST http://localhost:9090/-/reload`.

## Editing the dashboards

The JSON under `grafana/dashboards/` is **generated** — edit
`scripts/gen-dashboards.py` (stdlib only) and regenerate:

```bash
python3 scripts/gen-dashboards.py
```

Grafana reloads provisioned dashboards within ~30 s. You can also tweak live in
the UI to experiment, then fold the change back into the generator.

## Troubleshooting

- **A target is `down` at http://localhost:9090/targets.** Normal for exporters
  you aren't running (`nvidia_gpu` without an NVIDIA card, the native `node`
  target when you use the containerised one).
- **GPU row empty.** No NVIDIA card or `nvidia-smi` not on PATH.
  `start.sh` picks the container or native GPU exporter automatically; if you ran
  compose directly without a GPU exporter, use `start.sh` instead (or
  `./scripts/run-exporters.sh` to add just the native GPU exporter).
- **`start.sh` exits with "Can't talk to the Docker daemon".** Docker isn't
  running or the user isn't in the `docker` group — `sudo systemctl start
  docker`, or `sudo usermod -aG docker $USER` then re-login.
- **Grafana won't start / "address already in use".** Something holds 3000 or
  9090 — set `GRAFANA_PORT` / `PROM_PORT` in `.env` and start again. LeSysBot reads
  `GRAFANA_PORT` back, so the status screen and `share_dashboard` follow the move.
- **Metrics missing despite an exporter running.** A firewall (`ufw`) blocks
  container→host; that's why the stack runs on the **host network**. Use
  `./scripts/start.sh` (or plain `docker compose up -d` in `monitoring/`), never
  a bridge network of your own.
- **Grafana login fails after wrong tries.** Brute-force throttling returns 401
  for a few minutes. Wait, or `docker restart lesysbot-grafana`. Reset the
  password with the `grafana cli` command above.
- **Don't mix GPU paths.** The containerised (`--profile gpu`) and native
  (`run-exporters.sh`) GPU exporters both want port 9835 — run only one.
- **Reset everything incl. stored history:**
  `docker compose --profile gpu down -v`. `-v` wipes the data volumes.

## Share a snapshot from chat

The bundled **`share-dashboard`** tool (in `tools/share-dashboard/`) lets a user
say *"share me the dashboard"* and get back a public link — it publishes a
point-in-time **snapshot** (current graphs baked in as data) *through Grafana* to
`snapshots.raintank.io`, and can list/delete shares:

- `share_dashboard(expiration)` — `expiration` is `1h`/`6h`/`12h`/`1d`/`7d`/`30d`/`never` (default `1h`); returns the public URL.
- `list_snapshots()` — the snapshots Grafana currently holds (its `/dashboard/snapshots` registry), plus any still-live ones Grafana has pruned but the tool still tracks, each with its link and time left.
- `delete_snapshot(which)` — by number (from the list), snapshot key, or `all`; removes it from Grafana **and** raintank.

It needs the monitoring stack running and finds Grafana by probing `GRAFANA_PORT`
from `monitoring/.env`, then `localhost:3000`/`3001`, verifying each answers as
Grafana (a stale `LESYSBOT_GRAFANA_URL` falls back to the same probe),
authenticating with `LESYSBOT_GRAFANA_USER` /
`LESYSBOT_GRAFANA_PASSWORD` (default `admin`/`admin`). `lesysbot setup` prompts for
these and saves them to **`~/.lesysbot/grafana.env`**, which the bot loads into its
environment at startup — so edit that file (or set the vars directly) to change the
Grafana login or point `LESYSBOT_GRAFANA_URL` at another port/host. Shares are a **public** copy of the
metrics. Two caveats worth relaying to users: raintank may serve a *cached* copy for
up to ~1h after deletion, and a snapshot published from Grafana's own browser button
(not through the bot) has no delete key the tool can use, so it only clears at its
expiry. Full details: `tools/share-dashboard/README.md`.

## Related

- Operate the bot itself as a background service: **[manage-service](../manage-service/SKILL.md)**.
- General "it's broken" flow for the bot (not this stack): **[troubleshoot-lesysbot](../troubleshoot-lesysbot/SKILL.md)**.
- Full human guide: `monitoring/README.md` in the repo.
