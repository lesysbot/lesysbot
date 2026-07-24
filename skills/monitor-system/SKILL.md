---
name: monitor-system
description: Run LeSysBot's optional Prometheus + Grafana "System Overview" stack that records CPU, memory, disk, network (Ethernet/Wifi), temperatures (CPU/disk/GPU/sensors) and NVIDIA GPU as time series on ready-made Grafana dashboards. Cross-platform (Linux/macOS/Windows), localhost-only, no sudo. Use when asked to "monitor my system", "see CPU/GPU/temperature graphs", "set up Grafana/Prometheus", "system dashboard", or "record hardware metrics over time".
---

# System Overview — Prometheus + Grafana

LeSysBot ships an **optional, self-contained monitoring stack** in the
`monitoring/` folder of the repo. It records the machine's **CPU, memory, disk,
network (per interface — Ethernet & Wifi), temperatures and GPU** as Prometheus
time series and shows them on two pre-built Grafana dashboards.

Key properties to know before you start:

- **Separate from the bot.** The LeSysBot process still opens no network
  listener; this is a companion the user starts by hand. Everything it exposes
  binds to **`127.0.0.1` only** (nothing on the LAN) and needs **no sudo/admin**.
- **Standard components only** — Prometheus, Grafana, `node_exporter`,
  `windows_exporter`, `nvidia_gpu_exporter`. Nothing custom to trust.
- **The only prerequisite is Docker** (Compose v2). Prometheus, Grafana and the
  exporters download and configure themselves on first start.

## Prerequisite: Docker

```bash
docker compose version      # need "v2.x"; if missing, install Docker first
```

Install if absent: Docker Desktop on
[Windows](https://docs.docker.com/desktop/install/windows-install/) /
[macOS](https://docs.docker.com/desktop/install/mac-install/), or
[Docker Engine](https://docs.docker.com/engine/install/) on Linux
(`sudo usermod -aG docker $USER`, then re-login).

**Get the files.** The stack lives in the repo's `monitoring/` folder. If the
user installed LeSysBot with `pip` (no checkout), fetch it first:

```bash
git clone https://github.com/lesysbot/lesysbot && cd lesysbot/monitoring
```

Run every command below from that `monitoring/` folder. It is self-contained —
copying just that folder is enough.

## Start it (one command per OS)

Run from the repo's `monitoring/` folder.

| OS | Start | Stop |
|---|---|---|
| **Linux** | `./scripts/start.sh` | `./scripts/start.sh down` |
| **macOS** | `./scripts/start.sh` | `./scripts/start.sh down` |
| **Windows** (PowerShell) | `.\scripts\start.ps1` | `.\scripts\start.ps1 down` |

`start.sh`/`start.ps1` auto-detect the OS and the NVIDIA GPU and do the right
thing. Then open **http://localhost:3000** (login `admin` / `admin`). The two
dashboards are in the **LeSysBot** folder in Grafana.

**What the start scripts do under the hood** (useful when debugging):

- **Linux** — runs Prometheus + Grafana + `node-exporter` all on the **host
  network**, bound to localhost (`docker compose -f docker-compose.linux.yml up
  -d`). Host networking is required so `node_exporter` sees the real NICs and to
  avoid the `ufw`/firewall block on container→host traffic. **GPU is automatic:**
  `start.sh` adds `--profile gpu` (containerised exporter) when the Docker NVIDIA
  runtime is present, else falls back to a native GPU exporter
  (`run-exporters.sh`) — no nvidia-container-toolkit required either way; no GPU
  → skipped.
- **macOS / Windows** — Docker Desktop can't see the real host from its VM, so
  exporters run **natively** (`scripts/run-exporters.sh` /
  `run-exporters.ps1`, auto-downloaded), and Prometheus + Grafana run in
  containers that scrape them via `host.docker.internal`
  (`docker compose up -d`).

## What you get

**One dashboard**, matching the OS you started — only that one is provisioned
(the compose file mounts a single dashboard JSON), so a Linux box never shows an
empty "System Overview — Windows":

| Started on… | Dashboard | Exporter |
|---|---|---|
| Linux / macOS | **System Overview — Linux / macOS** | `node_exporter` |
| Windows | **System Overview — Windows** | `windows_exporter` |

Both JSON files always exist under `grafana/dashboards/`; the selector is the
`DASH_JSON` env var on the bridge compose (`start.ps1` sets it to the Windows
one). It covers: **CPU** (busy %, per-mode, load, cores) · **Memory** (used/cached,
swap/commit) · **Disk** (used % per mount, read/write) · **Network** per
interface (the interface name distinguishes Ethernet from Wifi) ·
**Temperatures** · **GPU** (NVIDIA: util, memory, temp, power).

### Temperature sensor coverage (per OS)

Only what the kernel exposes without sudo is shown:

| Sensor | Linux | macOS | Windows |
|---|---|---|---|
| **GPU** (NVIDIA) | yes | yes | yes |
| **CPU** (package + cores) | yes (`coretemp`/`k10temp`) | no | only if ACPI reports it |
| **Disk** (NVMe/SATA) | yes (`nvme`/`drivetemp`) | no | no |
| **ACPI / chipset / Wifi radio** | yes (thermal zones) | no | ACPI zone, often empty on desktops |

- **Linux** is fullest. A SATA drive temp may need `sudo modprobe drivetemp`
  once; NVMe needs nothing. Panels for sensors the hardware lacks stay empty.
- **macOS** exposes no component temps via `node_exporter` (GPU only, and most
  Macs have no NVIDIA card) — those panels stay empty; that's expected.
- **Windows** shows ACPI thermal-zone temps when firmware provides them (laptops
  usually, desktops rarely). Per-component CPU/disk temps need a helper like
  LibreHardwareMonitor — not bundled.

## Ports, credentials, configuration

Everything binds to loopback. Grafana `127.0.0.1:3000`, Prometheus
`127.0.0.1:9090` (`/targets` shows exporter health), exporters on
`:9100`/`:9182`/`:9835`.

- **Login:** `admin` / `admin`. **Change it** before exposing Grafana anywhere.
- **Override defaults:** copy `monitoring/.env.example` → `monitoring/.env`
  (git-ignored) and set `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_PORT`, `PROM_PORT`,
  `PROM_RETENTION` (how long history is kept). `GRAFANA_ADMIN_PASSWORD` only
  applies on the **first** Grafana start; to change it later use the Grafana UI
  or `docker exec lesysbot-grafana grafana cli admin reset-admin-password NEW`.
- **Add another host/exporter:** add its `host:port` to the right job in
  `prometheus/prometheus.yml` (macOS/Windows) or `prometheus.linux.yml` (Linux),
  then `curl -X POST http://localhost:9090/-/reload`.

## Editing the dashboards

The JSON under `grafana/dashboards/` is **generated** — edit
`scripts/gen-dashboards.py` (stdlib only) and regenerate so both dashboards stay
consistent:

```bash
python3 scripts/gen-dashboards.py
```

Grafana reloads provisioned dashboards within ~30 s. You can also tweak live in
the UI to experiment, then fold the change back into the generator.

## Troubleshooting

- **A target is `down` at http://localhost:9090/targets.** Normal for exporters
  you aren't running (`windows` on Linux/macOS, `nvidia_gpu` without an NVIDIA
  card, the native `node` target when you use the containerised one). Only your
  OS's exporter must be `up`.
- **GPU row empty.** No NVIDIA card or `nvidia-smi` not on PATH. On Linux,
  `start.sh` picks the container or native GPU exporter automatically; if you ran
  compose directly without a GPU exporter, use `start.sh` instead (or
  `./scripts/run-exporters.sh` to add just the native GPU exporter).
- **`start.sh`/`start.ps1` exits with "Can't talk to the Docker daemon".** Docker
  isn't running or the user isn't in the `docker` group — start Docker Desktop /
  `sudo systemctl start docker`, or `sudo usermod -aG docker $USER` then re-login.
- **Grafana won't start / "address already in use".** Something holds 3000 or
  9090 — set `GRAFANA_PORT` / `PROM_PORT` in `.env` and start again.
- **Linux metrics missing despite an exporter running.** A firewall (`ufw`)
  blocks container→host; that's why Linux uses the **host-network** stack. Use
  `./scripts/start.sh` (or `docker-compose.linux.yml`), never the bridge
  `docker-compose.yml`, on Linux.
- **Grafana login fails after wrong tries.** Brute-force throttling returns 401
  for a few minutes. Wait, or `docker restart lesysbot-grafana`. Reset the
  password with the `grafana cli` command above.
- **Don't mix GPU paths.** The containerised (`--profile gpu`) and native
  (`run-exporters.sh`) GPU exporters both want port 9835 — run only one.
- **Reset everything incl. stored history:**
  `docker compose -f docker-compose.linux.yml --profile gpu down -v` (Linux) or
  `docker compose down -v` (macOS/Windows). `-v` wipes the data volumes.

## Share a snapshot from chat

The bundled **`share-dashboard`** tool (in `tools/share-dashboard/`) lets a user
say *"share me the dashboard"* and get back a public link — it publishes a
point-in-time **snapshot** (current graphs baked in as data) *through Grafana* to
`snapshots.raintank.io`, and can list/delete shares:

- `share_dashboard(expiration)` — `expiration` is `1h`/`6h`/`12h`/`1d`/`7d`/`30d`/`never` (default `1h`); returns the public URL.
- `list_snapshots()` — the snapshots Grafana currently holds (its `/dashboard/snapshots` registry), plus any still-live ones Grafana has pruned but the tool still tracks, each with its link and time left.
- `delete_snapshot(which)` — by number (from the list), snapshot key, or `all`; removes it from Grafana **and** raintank.

It needs the monitoring stack running and reaches Grafana at `http://localhost:3000`
by default (auto-probing 3001 too). If Grafana runs on another port/host, set
`LESYSBOT_GRAFANA_URL` in the bot's environment. Shares are a **public** copy of the
metrics. Two caveats worth relaying to users: raintank may serve a *cached* copy for
up to ~1h after deletion, and a snapshot published from Grafana's own browser button
(not through the bot) has no delete key the tool can use, so it only clears at its
expiry. Full details: `tools/share-dashboard/README.md`.

## Related

- Operate the bot itself as a background service: **[manage-service](../manage-service/SKILL.md)**.
- General "it's broken" flow for the bot (not this stack): **[troubleshoot-lesysbot](../troubleshoot-lesysbot/SKILL.md)**.
- Full human guide: `monitoring/README.md` in the repo.
