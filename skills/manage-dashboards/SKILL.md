---
name: manage-dashboards
description: Run LeSysBot's default Prometheus + Grafana "System Overview" stack that records CPU, memory, disk, network (Ethernet/Wifi), temperatures (CPU/disk/GPU/sensors) and NVIDIA GPU as time series on ready-made Grafana dashboards. Cross-platform (Linux/macOS/Windows), localhost-only, no sudo. Use when asked to "monitor my system", "see CPU/GPU/temperature graphs", "set up Grafana/Prometheus", "system dashboard", or "record hardware metrics over time".
---

# System Overview — Prometheus + Grafana

LeSysBot ships a **standard, self-contained dashboard stack** in the
`dashboard/` folder of the repo. It records the machine's **CPU, memory, disk,
network (per interface — Ethernet & Wifi), temperatures and GPU** as Prometheus
time series and shows them on two pre-built Grafana dashboards.

`lesysbot setup` (run by the installer) seeds this stack into
`~/.lesysbot/dashboard` and gets the user to a Grafana dashboard at
**http://localhost:3000** — the mechanism is OS-specific:
- **Linux** — if Docker is running, setup *asks* whether to auto-start the
  bundled stack now or leave it for manual start; otherwise it prints the no-sudo
  steps to get Docker ready.
- **macOS** — setup does *not* require Docker Desktop; it asks whether to install
  now and then runs `scripts/install-macos.sh`, which `brew install`s
  `grafana`/`prometheus`/`node_exporter`, provisions the datasource + dashboard,
  sets the admin password, and starts all three under `brew services`. Without
  Homebrew it falls back to the native-Grafana instructions.
- **Windows** — setup does *not* require Docker Desktop; it instructs a
  **native Grafana install** from `https://grafana.com/grafana/download` and how
  to connect it (auto-detected on `localhost:3000`, else `LESYSBOT_GRAFANA_URL`),
  and mentions the Docker stack only as a shortcut when Docker is already running.

Use the steps below to start/stop the stack by hand, seed it on a box where the
prerequisite arrived later, or reconfigure it. `LESYSBOT_SKIP_DASHBOARD=1`
before setup skips the step entirely.

Key properties to know before you start:

- **Separate from the bot.** This stack runs as its own processes; LeSysBot's
  only listener is its localhost control panel (port 8700). Everything it
  exposes binds to **`127.0.0.1` only** (nothing on the LAN) and needs **no
  sudo/admin**.
- **Standard components only** — Prometheus, Grafana, `node_exporter`,
  `windows_exporter`, `nvidia_gpu_exporter`. Nothing custom to trust.
- **One prerequisite per OS** — Homebrew on macOS, Docker (Compose v2) on Linux
  and Windows. Prometheus, Grafana and the exporters install and configure
  themselves on first start.

## Prerequisite

**macOS — Homebrew.** `brew --version`; install from https://brew.sh if absent.
Nothing else: no Docker Desktop.

**Linux / Windows — Docker.**

```bash
docker compose version      # need "v2.x"; if missing, install Docker first
```

Install if absent:
[Docker Engine](https://docs.docker.com/engine/install/) on Linux
(`sudo usermod -aG docker $USER`, then re-login), or
[Docker Desktop](https://docs.docker.com/desktop/install/windows-install/) on
Windows.

**Get the files.** The stack lives in the repo's `dashboard/` folder. If the
user installed LeSysBot with `pip` (no checkout), fetch it first:

```bash
git clone https://github.com/lesysbot/lesysbot && cd lesysbot/monitoring
```

Run every command below from that `dashboard/` folder. It is self-contained —
copying just that folder is enough.

## Start it (one command per OS)

Run from the repo's `dashboard/` folder.

| OS | Start | Stop |
|---|---|---|
| **macOS** | `./scripts/install-macos.sh` | `./scripts/install-macos.sh down` |
| **Linux** | `./scripts/start.sh` | `./scripts/start.sh down` |
| **Windows** (PowerShell) | `.\scripts\start.ps1` | `.\scripts\start.ps1 down` |

The scripts auto-detect the OS and the NVIDIA GPU and do the right thing. Then
open **http://localhost:3000** (login `admin` / the password in `.env`). The
dashboard is in the **LeSysBot** folder in Grafana.

On macOS the Docker stack (`./scripts/start.sh`) still works if the user prefers
containers — but run one or the other, never both: they bind the same ports, and
`install-macos.sh` refuses to start when it sees the containers running.

**What the start scripts do under the hood** (useful when debugging):

- **macOS (`install-macos.sh`)** — no Docker at all. `brew install`s the three
  formulae, generates `monitoring/native/` (Prometheus scrape config on plain
  `localhost`, Grafana provisioning with the datasource URL baked in, and a
  dashboards folder holding only the macOS JSON), points
  `$(brew --prefix)/etc/{prometheus,node_exporter}.args` at it, appends a marked
  block to `grafana.ini` (`[paths] provisioning`, port, hardening), sets the
  admin password with `grafana cli admin reset-admin-password`, and
  `brew services restart`s all three. Re-running is safe and idempotent; ports
  and the admin login come from `dashboard/.env`, same as the Docker stack.

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
| Linux | **System Overview — Linux** | `node_exporter` |
| macOS (`install-macos.sh` or Docker) | **System Overview — macOS (Apple Silicon \| Intel)** | `node_exporter` (+ `macos-metrics.py` natively) |
| Windows | **System Overview — Windows** | `windows_exporter` |

It covers: **CPU** (busy %, per-mode, load, cores) · **Memory** (used/cached,
swap/commit) · **Disk** (used % per mount, read/write) · **Network** per
interface (the interface name distinguishes Ethernet from Wifi) ·
**Temperatures** · **GPU** (NVIDIA: util, memory, temp, power).

**Every start script generates its dashboard rather than copying one**, because a
panel querying a metric the host can't produce looks identical to a broken panel.
Each probes first, then calls `gen-dashboards.py --host H --have CAPS --out F`:

| OS | Probe | Capabilities it can pass |
|---|---|---|
| Linux (`start.sh`) | chip names in `/sys/class/hwmon/*/name`, `/sys/class/thermal/`, `nvidia-smi` | `cpu_temp`, `disk_temp`, `amd_gpu`, `thermal_zone`, `nvidia` |
| macOS (`install-macos.sh`, `start.sh`) | `uname -m`, `nvidia-smi` | `intel`, `nvidia` |
| Windows (`start.ps1`) | the **running** `windows_exporter`'s `/metrics`, `nvidia-smi`, `Win32_VideoController` | `thermalzone`, `nvidia` |

Key invariants when changing this:

- **NVIDIA is keyed on `nvidia-smi`, never on the card.** `nvidia_gpu_exporter`
  shells out to it, so a GPU with no driver can't be scraped by anything. Each
  script detects the *hardware* separately only to explain the omission.
- **Windows thermalzone must be probed live.** Whether it returns anything is a
  firmware property, not an OS one, so no static rule is correct.
- Unknown capabilities are a **usage error** in `gen-dashboards.py`, so a typo in
  a start script fails loudly instead of dropping a row.
- Generated files are `grafana/dashboards/generated-*.json` (git-ignored),
  selected through `DASH_JSON` in both compose files. The committed portable
  JSONs are the fallback when the host has no `python3` — each script warns when
  it falls back. **A user reporting whole empty rows is usually on that
  fallback.**

### Temperature sensor coverage (per OS)

Only what the kernel exposes without sudo is shown:

| Sensor | Linux | macOS | Windows |
|---|---|---|---|
| **GPU** (NVIDIA) | yes | no macOS driver since Mojave | yes |
| **CPU** (package + cores) | yes (`coretemp`/`k10temp`) | needs a helper (see below) | only if ACPI reports it |
| **Disk** (NVMe/SATA) | yes (`nvme`/`drivetemp`) | no | no |
| **Battery** (laptops) | — | yes (`ioreg`) | — |
| **CPU throttling** (not degrees) | — | Intel only (`node_thermal_cpu_*`) | — |
| **ACPI / chipset / Wifi radio** | yes (thermal zones) | no | ACPI zone, often empty on desktops |

- **Linux** is fullest. A SATA drive temp may need `sudo modprobe drivetemp`
  once; NVMe needs nothing. Panels for sensors the hardware lacks stay empty.
- **macOS** gets no temperature from `node_exporter` itself — no GPU support, and
  its `thermal` collector reports CPU *throttling* rather than degrees, through
  an Intel-only API. `scripts/macos-metrics.py` (installed and scheduled by
  `install-macos.sh`, launchd every 15s, served via node_exporter's textfile
  collector) supplies `macos_gpu_utilization_ratio`, `macos_gpu_memory_bytes` and
  `macos_battery_temperature_celsius` from `ioreg`, with **no sudo and no extra
  software**. CPU/GPU **die** temperature is not available unprivileged — the
  collector picks it up only if `smctemp` or `macmon` is installed. The installer
  now **offers** to install one (defaulting to no, and offering only `smctemp` on
  Intel since `macmon` is arm64-only); `LESYSBOT_TEMP_HELPER=macmon|smctemp|none`
  answers up front, and is what an unattended install uses. Until one exists
  those two tiles stay empty and that is expected, not a fault. Debug with
  `python3 scripts/macos-metrics.py --stdout` and
  `./scripts/install-macos.sh status`, whose first three lines report chip,
  NVIDIA and helper, then the sample's age — a stale textfile is served
  indefinitely after the collector dies.
- **Windows** shows ACPI thermal-zone temps when firmware provides them (laptops
  usually, desktops rarely). Per-component CPU/disk temps need a helper like
  LibreHardwareMonitor — not bundled.

## Ports, credentials, configuration

Everything binds to loopback. Grafana `127.0.0.1:3000`, Prometheus
`127.0.0.1:9090` (`/targets` shows exporter health), exporters on
`:9100`/`:9182`/`:9835`.

- **Login:** `admin` / `admin`. **Change it** before exposing Grafana anywhere.
- **Override defaults:** copy `dashboard/.env.example` → `dashboard/.env`
  (git-ignored) and set `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_PORT`, `PROM_PORT`,
  `PROM_RETENTION` (how long history is kept). `GRAFANA_ADMIN_PASSWORD` only
  applies on the **first** Grafana start; to change it later use the Grafana UI
  or `docker exec lesysbot-grafana grafana cli admin reset-admin-password NEW`.
- **Add another host/exporter:** add its `host:port` to the right job in
  `prometheus/prometheus.yml` (macOS/Windows) or `prometheus.linux.yml` (Linux),
  then `curl -X POST http://localhost:9090/-/reload`.

## Editing the dashboards

The JSON under `grafana/dashboards/` is **generated** — edit
`scripts/gen-dashboards.py` (stdlib only) and regenerate so every dashboard stays
consistent. Never hand-edit the JSON:

```bash
python3 scripts/gen-dashboards.py                       # the committed, portable JSONs
python3 scripts/gen-dashboards.py --host {linux|macos|windows} --have CAPS --out FILE
```

The second form is what the start scripts run; the per-host cuts are generated
rather than committed so one generator still covers every hardware combination.
`tests/test_gen_dashboards.py` pins the inclusion/exclusion decisions per cut
(and fails if the committed JSON goes stale — regenerate after touching the
generator); `tests/test_start_detect.py` sources `start.sh` against a fixture
`/sys` tree (`SYSFS_ROOT`) to pin the chip-name → capability mapping.

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
  9090 — set `GRAFANA_PORT` / `PROM_PORT` in `.env` and start again. LeSysBot reads
  `GRAFANA_PORT` back, so the status screen and `share_dashboard` follow the move.
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

It needs the dashboard stack running and finds Grafana by probing `GRAFANA_PORT`
from `dashboard/.env`, then `localhost:3000`/`3001`, verifying each answers as
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
- Full human guide: `dashboard/README.md` in the repo.
