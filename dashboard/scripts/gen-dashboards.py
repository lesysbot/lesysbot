#!/usr/bin/env python3
"""Generate the bundled Grafana dashboards for the LeSysBot dashboard stack.

This is the source of truth for the JSON under ``dashboard/grafana/dashboards/``.
Editing the JSON by hand is fine for a quick tweak, but prefer changing this file
and re-running it so the dashboards stay consistent:

    python3 dashboard/scripts/gen-dashboards.py

It writes:
  * system-overview-linux-macos.json  — node_exporter    (Linux / macOS)  + GPU
  * system-overview-windows.json      — windows_exporter  (Windows)        + GPU

Those two are the *portable* dashboards: one JSON has to serve every host, so
panels an OS can't fill are simply empty there. The start scripts instead probe
the machine they're on and ask for a dashboard cut to it:

    python3 gen-dashboards.py --host linux   --have cpu_temp,disk_temp,nvidia --out PATH
    python3 gen-dashboards.py --host macos   --have intel,nvidia              --out PATH
    python3 gen-dashboards.py --host windows --have thermalzone               --out PATH

Each `--have` capability is something the caller *verified* (an hwmon chip of
that family exists, nvidia-smi answers, the exporter really serves that metric),
and a panel is included only when something can fill it. The point is that an
empty panel then means a fault worth chasing rather than "this OS never had
that sensor" — which is indistinguishable to the person looking at it.

Generating per machine is what keeps this file the single source of truth without
committing a JSON for every hardware combination. `scripts/start.sh` (Linux),
`scripts/start.ps1` (Windows) and `scripts/install-macos.sh` (macOS) each do the
probing; see `CAPABILITIES` below for what they may pass.

Every panel binds to the provisioned Prometheus datasource (uid "prometheus").
No third-party libraries — stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus"}
OUT = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"

# NVIDIA metric names as exported by nvidia_gpu_exporter (utkuozdemir).
GPU_UTIL = "nvidia_smi_utilization_gpu_ratio"        # 0..1
GPU_MEM_USED = "nvidia_smi_memory_used_bytes"
GPU_MEM_TOTAL = "nvidia_smi_memory_total_bytes"
GPU_TEMP = "nvidia_smi_temperature_gpu"              # °C
GPU_POWER = "nvidia_smi_power_draw_watts"            # W
GPU_LEGEND = "{{uuid}}"  # nvidia_gpu_exporter labels every series by GPU uuid only

# macOS-only series, written by scripts/macos-metrics.py into node_exporter's
# textfile collector. The die temperatures are the two that need a helper
# (smctemp / macmon) — everything else here works out of the box.
MAC_CPU_TEMP = "macos_cpu_temperature_celsius"
MAC_GPU_TEMP = "macos_gpu_temperature_celsius"
MAC_BATT_TEMP = "macos_battery_temperature_celsius"
MAC_LAST_RUN = "macos_metrics_last_run_timestamp_seconds"

# Why a Mac tile can be empty, in the one place a reader will look for it.
MAC_DIE_HELP = (
    "Apple publishes die temperature only through IOReport (a private framework) "
    "or root-only powermetrics, and LeSysBot never asks for sudo — so this needs "
    "a small helper. Install one and it fills in within 15s:\n\n"
    "    brew install vladkens/tap/macmon      (Apple Silicon)\n"
    "    brew install narugit/tap/smctemp      (Apple Silicon or Intel)\n\n"
    "Empty without one is expected, not a fault."
)


class Layout:
    """Simple 24-column auto-flow layout: append panels, rows wrap for you."""

    def __init__(self) -> None:
        self.panels: list[dict] = []
        self._x = 0
        self._y = 0
        self._row_h = 0
        self._id = 0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def row(self, title: str) -> None:
        if self._x != 0:
            self._y += self._row_h
            self._x = 0
            self._row_h = 0
        self.panels.append({
            "type": "row",
            "title": title,
            "collapsed": False,
            "id": self._next_id(),
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self._y},
            "panels": [],
        })
        self._y += 1

    def _place(self, w: int, h: int) -> dict:
        if self._x + w > 24:
            self._y += self._row_h
            self._x = 0
            self._row_h = 0
        pos = {"h": h, "w": w, "x": self._x, "y": self._y}
        self._x += w
        self._row_h = max(self._row_h, h)
        return pos

    def _targets(self, targets: list[tuple[str, str]]) -> list[dict]:
        out = []
        for i, (expr, legend) in enumerate(targets):
            out.append({
                "refId": chr(ord("A") + i),
                "datasource": DS,
                "expr": expr,
                "legendFormat": legend,
            })
        return out

    def stat(self, title, targets, unit, w=4, h=4, thresholds=None, gauge=False,
             decimals=None, minv=None, maxv=None, desc=None):
        fc = {
            "unit": unit,
            "thresholds": {
                "mode": "absolute",
                "steps": thresholds or [{"color": "green", "value": None}],
            },
        }
        if decimals is not None:
            fc["decimals"] = decimals
        if minv is not None:
            fc["min"] = minv
        if maxv is not None:
            fc["max"] = maxv
        self.panels.append({
            "type": "gauge" if gauge else "stat",
            "title": title,
            "description": desc or "",
            "id": self._next_id(),
            "datasource": DS,
            "gridPos": self._place(w, h),
            "targets": self._targets(targets),
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                "orientation": "auto",
                "colorMode": "value" if not gauge else "none",
                "graphMode": "area" if not gauge else "none",
                "textMode": "auto",
                "showThresholdLabels": False,
                "showThresholdMarkers": True,
            },
            "fieldConfig": {"defaults": fc, "overrides": []},
        })

    def ts(self, title, targets, unit, w=12, h=8, stack=False, fill=10,
           minv=None, decimals=None, desc=None):
        custom = {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 1,
            "fillOpacity": fill,
            "gradientMode": "opacity",
            "spanNulls": False,
            "showPoints": "never",
            "stacking": {"mode": "normal" if stack else "none", "group": "A"},
            "axisPlacement": "auto",
        }
        defaults = {"unit": unit, "custom": custom}
        if minv is not None:
            defaults["min"] = minv
        if decimals is not None:
            defaults["decimals"] = decimals
        self.panels.append({
            "type": "timeseries",
            "title": title,
            "description": desc or "",
            "id": self._next_id(),
            "datasource": DS,
            "gridPos": self._place(w, h),
            "targets": self._targets(targets),
            "options": {
                "legend": {"displayMode": "table", "placement": "bottom",
                           "calcs": ["mean", "max", "lastNotNull"]},
                "tooltip": {"mode": "multi", "sort": "desc"},
            },
            "fieldConfig": {"defaults": defaults, "overrides": []},
        })


def dashboard(title, uid, layout, extra_vars=None):
    templating = [{
        "type": "query",
        "name": "instance",
        "label": "Host",
        "datasource": DS,
        "query": {"query": 'label_values(up{job=~"node|windows"}, instance)',
                  "refId": "StandardVariableQuery"},
        "refresh": 2,
        "includeAll": True,
        "multi": True,
        "current": {"text": "All", "value": "$__all"},
        "sort": 1,
    }]
    if extra_vars:
        templating.extend(extra_vars)
    return {
        "uid": uid,
        "title": title,
        "tags": ["lesysbot", "system-overview"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "editable": True,
        "refresh": "15s",
        "time": {"from": "now-1h", "to": "now"},
        "templating": {"list": templating},
        "panels": layout.panels,
        "annotations": {"list": []},
    }


# ---------------------------------------------------------------- percentages
PCT = [
    {"color": "green", "value": None},
    {"color": "yellow", "value": 70},
    {"color": "red", "value": 90},
]
TEMP = [
    {"color": "green", "value": None},
    {"color": "yellow", "value": 70},
    {"color": "red", "value": 85},
]

# net-device filters: keep physical NICs, drop loopback / virtual / container ifaces
NODE_NIC = 'device!~"lo|veth.*|docker.*|br-.*|virbr.*|tap.*|cali.*|flannel.*|cni.*"'


# hwmon join: attach the human-readable sensor label and chip name to each temp.
#   coretemp / k10temp / cpu_thermal = CPU (Intel / AMD / ARM)
#   nvme / drivetemp                 = disk (NVMe / SATA)
CPU_CHIPS = "coretemp|k10temp|cpu_thermal"
DISK_CHIPS = "nvme|drivetemp"
AMD_GPU_CHIPS = "amdgpu"
_LABELED = ("node_hwmon_temp_celsius"
            " * on(chip,sensor) group_left(label) node_hwmon_sensor_label"
            " * on(chip) group_left(chip_name) node_hwmon_chip_names")
_MAX_FOR = ("max(node_hwmon_temp_celsius"
            " * on(chip) group_left(chip_name) node_hwmon_chip_names{{chip_name=~\"{chips}\"}})")


# ------------------------------------------------------- sections shared by the
# portable Linux/macOS dashboard and the Mac-specific one. Only the sections
# whose queries are *identical* on both live here; Overview and Memory differ
# (Linux and macOS name their memory metrics differently) and stay per-flavour.
INST = '{instance=~"$instance"}'


def cpu_section(g: Layout) -> None:
    g.row("CPU & Load")
    g.ts("CPU Usage by Mode",
         [('avg by (mode) (rate(node_cpu_seconds_total{mode!="idle",instance=~"$instance"}[$__rate_interval])) * 100',
           "{{mode}}")], "percent", stack=True, minv=0)
    g.ts("Load Average",
         [(f'node_load1{INST}', "1m"), (f'node_load5{INST}', "5m"),
          (f'node_load15{INST}', "15m")], "short", fill=0, minv=0)


def swap_section(g: Layout, flavour: str) -> None:
    """Swap usage. Appended to whichever Memory row is already open.

    macOS' node_exporter names these differently from Linux' (lowercase
    ``swap_used``/``swap_total`` against ``SwapFree``/``SwapTotal``), which is why
    this panel used to read as "Linux only" — it wasn't, the query just never
    asked for the macOS names. ``flavour`` is "portable" (ask for both),
    "linux" or "macos".
    """
    mac_used = "node_memory_swap_used_bytes" + INST
    mac_total = "node_memory_swap_total_bytes" + INST
    lin_used = f'node_memory_SwapTotal_bytes{INST} - node_memory_SwapFree_bytes{INST}'
    lin_free = f'node_memory_SwapFree_bytes{INST}'
    if flavour == "macos":
        used, free = mac_used, f"{mac_total} - {mac_used}"
        desc = ("macOS compresses before it swaps, so steady non-zero swap with "
                "low pressure is normal — watch the trend, not the value.")
    elif flavour == "linux":
        used, free = lin_used, lin_free
        desc = "Empty means swap is off (or you're in a container without any)."
    else:
        used = f"{lin_used} or {mac_used}"
        free = f"{lin_free} or ({mac_total} - {mac_used})"
        desc = ("Linux and macOS name their swap metrics differently; each target "
                "`or`s both, so exactly one side answers on any given host. Empty "
                "means swap is off.")
    g.ts("Swap Usage", [(used, "used"), (free, "free")], "bytes", minv=0, desc=desc)


def disk_section(g: Layout) -> None:
    g.row("Disk")
    g.ts("Filesystem Used %",
         [('(1 - (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs|devtmpfs",instance=~"$instance"} '
           '/ node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs|devtmpfs",instance=~"$instance"})) * 100',
           "{{mountpoint}}")], "percent", fill=0, minv=0)
    g.ts("Disk I/O",
         [(f'rate(node_disk_read_bytes_total{INST}[$__rate_interval])', "{{device}} read"),
          (f'-rate(node_disk_written_bytes_total{INST}[$__rate_interval])', "{{device}} write")],
         "Bps")


def network_section(g: Layout) -> None:
    g.row("Network — Ethernet & Wifi (per interface)")
    g.ts("Network Received",
         [(f'rate(node_network_receive_bytes_total{{{NODE_NIC},instance=~"$instance"}}[$__rate_interval]) * 8',
           "{{device}}")], "bps", minv=0)
    g.ts("Network Transmitted",
         [(f'rate(node_network_transmit_bytes_total{{{NODE_NIC},instance=~"$instance"}}[$__rate_interval]) * 8',
           "{{device}}")], "bps", minv=0)


def temps_section_node(g: Layout) -> None:
    """CPU / disk / sensor temperatures (Linux hwmon + thermal zones, macOS ioreg)."""
    g.row("Temperatures — CPU / Disk / Sensors")
    # `or` chains the macOS reading onto the Linux one: exactly one of them has
    # data on any given host, so one panel serves both OSes. On macOS the CPU
    # tile needs a helper (see macos-metrics.py) — without it only the battery
    # tile fills in, which is still more than the nothing hwmon gives there.
    _MAC_DIE = ("On macOS this needs a helper — Apple publishes die temperature "
                "only through IOReport or root-only powermetrics. Install "
                "`smctemp` or `macmon` (see dashboard/README.md) and it fills in "
                "within 15s. Empty here is expected, not a fault.")
    g.stat("CPU Temperature",
           [(f"{_MAX_FOR.format(chips=CPU_CHIPS)} or macos_cpu_temperature_celsius",
             "cpu")],
           "celsius", w=6, thresholds=TEMP,
           desc="Linux: hottest hwmon CPU sensor (coretemp/k10temp/cpu_thermal). "
                + _MAC_DIE)
    g.stat("Disk Temperature", [(_MAX_FOR.format(chips=DISK_CHIPS), "disk")], "celsius",
           w=6, thresholds=TEMP,
           desc="NVMe / SATA drive temperature. Linux only — macOS and Windows "
                "expose no disk sensor without a third-party helper.")
    g.stat("GPU Temperature",
           [(f"max({GPU_TEMP}) or macos_gpu_temperature_celsius", "gpu")],
           "celsius", w=6, thresholds=TEMP,
           desc="NVIDIA GPUs report this directly. " + _MAC_DIE)
    g.stat("Battery Temperature", [("macos_battery_temperature_celsius", "battery")],
           "celsius", w=6, thresholds=TEMP,
           desc="macOS laptops only (AppleSmartBattery). Tracks chassis heat "
                "rather than the CPU die, so it moves slowly — good for 'is this "
                "machine cooking?', not for catching a short load spike.")
    g.ts("CPU Temperature (package & per-core)",
         [(f'{_LABELED}{{chip_name=~"{CPU_CHIPS}"}}', "{{label}}")], "celsius",
         minv=0, fill=0,
         desc="Package and per-core temperatures (Intel coretemp / AMD k10temp / ARM). Linux only.")
    g.ts("Disk Temperature",
         [(f'{_LABELED}{{chip_name=~"{DISK_CHIPS}"}}', "{{chip_name}} {{label}}")], "celsius",
         minv=0, fill=0,
         desc="NVMe (nvme) and SATA (drivetemp) drive temperatures. Linux only.")
    g.ts("Other Sensors — ACPI zone / chipset / Wifi radio / Mac battery",
         [("node_thermal_zone_temp", "{{type}} (zone {{zone}})"),
          ("macos_battery_temperature_celsius", "battery (macOS)"),
          ("macos_cpu_temperature_celsius", "CPU die (macOS)"),
          ("macos_gpu_temperature_celsius", "GPU die (macOS)")], "celsius",
         minv=0, fill=0,
         desc="Linux: ACPI thermal zones — CPU package (x86_pkg_temp), chassis "
              "(acpitz), Wifi radio (iwlwifi). macOS: battery temperature, plus "
              "CPU/GPU die temperatures when smctemp or macmon is installed "
              "(Apple publishes no die temperature without one).")


def temps_section_linux(g: Layout, caps: set[str]) -> None:
    """Temperatures on a known Linux host — only the chips it actually has.

    The portable row asks for every hwmon chip family and lets the misses render
    blank, which is right for a dashboard that has to serve any machine. Here the
    host was probed (``/sys/class/hwmon/*/name``), so a panel is included only
    when a chip that can answer it is present. A VM or a container host usually
    has none of them, in which case the whole row is skipped and the start script
    says why.
    """
    if not (caps & {"cpu_temp", "disk_temp", "thermal_zone", "amd_gpu", "nvidia"}):
        return
    g.row("Temperatures")
    tiles = []
    if "cpu_temp" in caps:
        tiles.append(("CPU Temperature", _MAX_FOR.format(chips=CPU_CHIPS), "cpu",
                      "Hottest hwmon CPU sensor (coretemp / k10temp / cpu_thermal)."))
    if "disk_temp" in caps:
        tiles.append(("Disk Temperature", _MAX_FOR.format(chips=DISK_CHIPS), "disk",
                      "Hottest NVMe or SATA drive."))
    if "amd_gpu" in caps:
        tiles.append(("AMD GPU Temperature", _MAX_FOR.format(chips=AMD_GPU_CHIPS), "gpu",
                      "amdgpu hwmon sensor — the driver's own reading, no exporter needed."))
    if "nvidia" in caps:
        tiles.append(("NVIDIA GPU Temperature", f"max({GPU_TEMP})", "gpu",
                      "Reported by nvidia-smi through nvidia_gpu_exporter."))
    width = 24 // max(len(tiles), 1)
    for title, expr, legend, desc in tiles:
        g.stat(title, [(expr, legend)], "celsius", w=width, thresholds=TEMP, desc=desc)

    if "cpu_temp" in caps:
        g.ts("CPU Temperature (package & per-core)",
             [(f'{_LABELED}{{chip_name=~"{CPU_CHIPS}"}}', "{{label}}")], "celsius",
             minv=0, fill=0,
             desc="Package and per-core temperatures (Intel coretemp / AMD k10temp / ARM cpu_thermal).")
    if "disk_temp" in caps:
        g.ts("Disk Temperature",
             [(f'{_LABELED}{{chip_name=~"{DISK_CHIPS}"}}', "{{chip_name}} {{label}}")],
             "celsius", minv=0, fill=0,
             desc="NVMe (nvme) and SATA (drivetemp) drive temperatures.")
    if "amd_gpu" in caps:
        g.ts("AMD GPU Temperature",
             [(f'{_LABELED}{{chip_name=~"{AMD_GPU_CHIPS}"}}', "{{label}}")], "celsius",
             minv=0, fill=0,
             desc="Edge, junction and memory sensors, depending on the card.")
    if "thermal_zone" in caps:
        g.ts("Other Sensors — ACPI zone / chipset / Wifi radio",
             [("node_thermal_zone_temp", "{{type}} (zone {{zone}})")], "celsius",
             minv=0, fill=0,
             desc="ACPI thermal zones: CPU package (x86_pkg_temp), chassis (acpitz), "
                  "Wifi radio (iwlwifi). What appears depends entirely on the firmware.")


def temps_section_macos(g: Layout, intel: bool) -> None:
    """Temperatures on a Mac — only the readings a Mac can actually produce.

    The portable dashboard's temperature row is mostly Linux hwmon panels that
    are structurally empty here (no hwmon, no disk sensor), which is the single
    biggest source of "my dashboard is broken" on macOS. This row drops them and
    keeps the four things a Mac answers: battery temperature, the two die
    temperatures when a helper is installed, and — on Intel only — node_exporter's
    thermal collector, which reports CPU *throttling* rather than a temperature
    (its underlying API is Intel-only; on Apple Silicon the collector reports
    failure, so those panels are omitted rather than left blank).
    """
    g.row("Temperatures — macOS")
    g.stat("CPU Die Temperature", [(MAC_CPU_TEMP, "cpu")], "celsius",
           w=6, thresholds=TEMP,
           desc="Hottest CPU die sensor. " + MAC_DIE_HELP)
    g.stat("GPU Die Temperature", [(MAC_GPU_TEMP, "gpu")], "celsius",
           w=6, thresholds=TEMP,
           desc="GPU die sensor. " + MAC_DIE_HELP)
    g.stat("Battery Temperature", [(MAC_BATT_TEMP, "battery")], "celsius",
           w=6, thresholds=TEMP,
           desc="AppleSmartBattery, so laptops only — a desktop Mac leaves this "
                "empty. Tracks chassis heat rather than the die, so it moves "
                "slowly: good for 'is this machine cooking?', not for catching a "
                "short load spike.")
    # Answers "why is this row empty?" without a trip to the logs: a .prom file
    # keeps being served after its writer dies, so the panels would otherwise
    # show a plausible frozen value instead of nothing.
    g.stat("Collector Age", [(f"time() - {MAC_LAST_RUN}", "age")], "s", w=6,
           thresholds=[{"color": "green", "value": None},
                       {"color": "yellow", "value": 60},
                       {"color": "red", "value": 300}],
           desc="How long ago scripts/macos-metrics.py last wrote a sample. It "
                "runs every 15s under launchd, so anything above a minute means "
                "the collector stopped and the GPU/temperature panels are stale:\n\n"
                "    launchctl print gui/$UID/com.lesysbot.macos-metrics")
    g.ts("Temperatures", [(MAC_BATT_TEMP, "battery"), (MAC_CPU_TEMP, "CPU die"),
                          (MAC_GPU_TEMP, "GPU die")], "celsius",
         w=24 if not intel else 12, minv=0, fill=0,
         desc="Battery is always available; the die temperatures appear once "
              "smctemp or macmon is installed.")
    if intel:
        # node_exporter's darwin thermal collector exposes throttling ratios, not
        # temperatures — useful, and this is the only dashboard that can show it.
        g.ts("CPU Thermal Throttling (Intel)",
             [("node_thermal_cpu_speed_limit_ratio * 100", "speed limit"),
              ("node_thermal_cpu_scheduler_limit_ratio * 100", "scheduler limit")],
             "percent", w=12, minv=0, fill=0,
             desc="node_exporter's thermal collector. 100% means unthrottled; a "
                  "dip means the SMC is holding the CPU back, usually on heat. "
                  "Intel Macs only — the API behind it does not exist on Apple "
                  "Silicon.")


def temps_section_windows(g: Layout, caps: set[str] | None = None) -> None:
    """Best-effort temperatures on Windows (ACPI thermal zones + GPU).

    ``caps is None`` builds the portable row (both panels, misses render blank).
    With capabilities probed from the running ``windows_exporter``, each panel is
    included only when something can answer it — on a desktop that usually means
    no thermal row at all, which is the honest outcome: Windows exposes no
    per-component CPU or disk temperature without a helper like
    LibreHardwareMonitor.
    """
    zones = caps is None or "thermalzone" in caps
    gpu = caps is None or "nvidia" in caps
    if not (zones or gpu):
        return
    title = ("Temperatures  (best-effort — ACPI thermalzone; often empty on desktops)"
             if caps is None else "Temperatures")
    g.row(title)
    if gpu:
        g.stat("GPU Temperature", [(f"max({GPU_TEMP})", "gpu")], "celsius",
               w=12 if zones else 24, thresholds=TEMP)
    if zones:
        g.stat("ACPI Zone (max)", [("max(windows_thermalzone_temperature_celsius)", "zone")],
               "celsius", w=12 if gpu else 24, thresholds=TEMP)
        g.ts("ACPI Thermal Zones",
             [("windows_thermalzone_temperature_celsius", "{{name}}")], "celsius",
             minv=0, fill=0,
             desc="windows_exporter thermalzone collector. Many desktops expose nothing here; "
                  "laptops usually do. Per-component CPU/disk temps on Windows need a tool like "
                  "LibreHardwareMonitor.")


def gpu_section(g: Layout, detected: bool = False) -> None:
    """GPU panels — identical on every OS (nvidia_gpu_exporter is cross-platform).

    ``detected`` drops the "down if no card" caveat from the row title: on a
    tailored cut this row is only present because nvidia-smi answered, so an
    empty row there really is a fault (usually the exporter not running).
    """
    g.row("GPU — NVIDIA" if detected
          else "GPU — NVIDIA (down if no NVIDIA card / exporter)")
    g.stat("GPU Utilization", [(f"{GPU_UTIL} * 100", GPU_LEGEND)], "percent",
           w=6, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("GPU Memory Used",
           [(f"{GPU_MEM_USED} / {GPU_MEM_TOTAL} * 100", GPU_LEGEND)], "percent",
           w=6, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("GPU Temperature", [(GPU_TEMP, GPU_LEGEND)], "celsius",
           w=6, thresholds=TEMP)
    g.stat("GPU Power Draw", [(GPU_POWER, GPU_LEGEND)], "watt", w=6,
           thresholds=[{"color": "green", "value": None}])
    g.ts("GPU Utilization", [(f"{GPU_UTIL} * 100", GPU_LEGEND)], "percent",
         minv=0)
    g.ts("GPU Memory Used", [(GPU_MEM_USED, GPU_LEGEND)], "bytes", minv=0)
    g.ts("GPU Temperature", [(GPU_TEMP, GPU_LEGEND)], "celsius", minv=0, fill=5)
    g.ts("GPU Power Draw", [(GPU_POWER, GPU_LEGEND)], "watt", minv=0)


def gpu_section_apple(g: Layout, title: str = "GPU — Apple (macOS only; empty elsewhere)") -> None:
    """Apple Silicon / Intel Mac GPU, from macos-metrics.py (ioreg).

    A row of its own rather than `or`-ed into the NVIDIA panels above: the two
    sources have different labels (`uuid` vs `engine`), so a merged panel would
    lose its legend on one OS or the other. Empty on Linux, exactly as the NVIDIA
    row is empty on a Mac — hence the title override for the Mac-only dashboard,
    where it is the *main* GPU row rather than the one that stays blank.
    """
    g.row(title)
    g.stat("GPU Utilization",
           [('macos_gpu_utilization_ratio{engine="device"} * 100', "gpu")], "percent",
           w=8, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("GPU Memory In Use", [('macos_gpu_memory_bytes{kind="in_use"}', "in use")],
           "bytes", w=8, thresholds=[{"color": "green", "value": None}])
    g.stat("GPU Memory Allocated",
           [('macos_gpu_memory_bytes{kind="allocated"}', "allocated")], "bytes",
           w=8, thresholds=[{"color": "green", "value": None}])
    g.ts("GPU Utilization — device / renderer / tiler",
         [("macos_gpu_utilization_ratio * 100", "{{engine}}")], "percent",
         minv=0,
         desc="IOAccelerator PerformanceStatistics. 'device' is overall busy time; "
              "'renderer' and 'tiler' are the two halves of Apple's tile-based "
              "pipeline. Apple exposes no per-process GPU split without sudo.")
    g.ts("GPU Memory", [("macos_gpu_memory_bytes", "{{kind}}")], "bytes", minv=0,
         desc="Apple GPUs share system memory, so this is a slice of RAM, not "
              "dedicated VRAM. 'allocated' is reserved, 'in use' is live.")


# =========================================================== Linux / macOS
def build_node() -> dict:
    g = Layout()
    inst = '{instance=~"$instance"}'

    g.row("Overview")
    g.stat("CPU Busy",
           [(f'100 - (avg(rate(node_cpu_seconds_total{{mode="idle",instance=~"$instance"}}[$__rate_interval])) * 100)',
             "cpu")],
           "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT)
    # Linux exposes MemAvailable/MemTotal; macOS node_exporter does not — it has
    # total/active/wired/compressed instead. `or` picks whichever set exists, so
    # one panel works on both OSes.
    g.stat("Memory Used",
           [(f'(1 - (node_memory_MemAvailable_bytes{inst} / node_memory_MemTotal_bytes{inst})) * 100'
             f' or (node_memory_active_bytes{inst} + node_memory_wired_bytes{inst}'
             f' + node_memory_compressed_bytes{inst}) / node_memory_total_bytes{inst} * 100',
             "mem")],
           "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("Root FS Used",
           [('(1 - (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs",instance=~"$instance"} '
             '/ node_filesystem_size_bytes{mountpoint="/",instance=~"$instance"})) * 100', "/")],
           "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("Uptime",
           [(f'node_time_seconds{inst} - node_boot_time_seconds{inst}', "uptime")],
           "s", w=4, thresholds=[{"color": "blue", "value": None}])
    g.stat("Load (1m)", [(f'node_load1{inst}', "load1")], "short", w=4,
           decimals=2, thresholds=[{"color": "green", "value": None}])
    g.stat("CPU Cores",
           [(f'count(count(node_cpu_seconds_total{inst}) by (cpu))', "cores")],
           "short", w=4, thresholds=[{"color": "blue", "value": None}])

    cpu_section(g)

    g.row("Memory")
    # Each target `or`s the Linux metric with its macOS equivalent, so the panel
    # is populated on both (only one side exists on any given host).
    g.ts("Memory Usage",
         [(f'(node_memory_MemTotal_bytes{inst} - node_memory_MemAvailable_bytes{inst})'
           f' or (node_memory_active_bytes{inst} + node_memory_wired_bytes{inst}'
           f' + node_memory_compressed_bytes{inst})', "used"),
          (f'node_memory_Cached_bytes{inst} or node_memory_inactive_bytes{inst}', "cached / inactive"),
          (f'node_memory_MemAvailable_bytes{inst} or node_memory_free_bytes{inst}', "available / free")],
         "bytes", minv=0)
    swap_section(g, "portable")

    disk_section(g)
    network_section(g)

    temps_section_node(g)
    gpu_section(g)
    gpu_section_apple(g)
    return dashboard("System Overview — Linux / macOS", "lesysbot-node", g)


# ==================================================== Linux (host-specific cut)
def build_linux(caps: set[str]) -> dict:
    """A dashboard for one Linux host, generated by scripts/start.sh at start-up.

    Same bargain as the macOS cut: the host was probed, so panels it cannot fill
    are left out rather than rendered blank. What `caps` can hold, and what
    start.sh probes to decide:

      cpu_temp / disk_temp / amd_gpu   an hwmon chip of that family exists
                                       under /sys/class/hwmon/*/name
      thermal_zone                     /sys/class/thermal/thermal_zone* exists
      nvidia                           nvidia-smi is on PATH

    The macOS `or` fallbacks are dropped too — on a known Linux host they only
    make the queries harder to read.
    """
    g = Layout()

    g.row("Overview")
    g.stat("CPU Busy",
           [('100 - (avg(rate(node_cpu_seconds_total{mode="idle",instance=~"$instance"}[$__rate_interval])) * 100)',
             "cpu")], "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("Memory Used",
           [(f'(1 - (node_memory_MemAvailable_bytes{INST} / node_memory_MemTotal_bytes{INST})) * 100',
             "mem")], "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("Root FS Used",
           [('(1 - (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay|squashfs",instance=~"$instance"} '
             '/ node_filesystem_size_bytes{mountpoint="/",instance=~"$instance"})) * 100', "/")],
           "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("Uptime",
           [(f'node_time_seconds{INST} - node_boot_time_seconds{INST}', "uptime")],
           "s", w=4, thresholds=[{"color": "blue", "value": None}])
    g.stat("Load (1m)", [(f'node_load1{INST}', "load1")], "short", w=4,
           decimals=2, thresholds=[{"color": "green", "value": None}])
    g.stat("CPU Cores",
           [(f'count(count(node_cpu_seconds_total{INST}) by (cpu))', "cores")],
           "short", w=4, thresholds=[{"color": "blue", "value": None}])

    cpu_section(g)

    g.row("Memory")
    g.ts("Memory Usage",
         [(f'node_memory_MemTotal_bytes{INST} - node_memory_MemAvailable_bytes{INST}', "used"),
          (f'node_memory_Cached_bytes{INST}', "cached"),
          (f'node_memory_MemAvailable_bytes{INST}', "available")], "bytes", minv=0)
    swap_section(g, "linux")

    disk_section(g)
    network_section(g)

    temps_section_linux(g, caps)
    if "nvidia" in caps:
        gpu_section(g, detected=True)
    return dashboard("System Overview — Linux", "lesysbot-node", g)


# ==================================================== macOS (host-specific cut)
def build_macos(intel: bool = False, nvidia: bool = False) -> dict:
    """A dashboard for one Mac, generated by scripts/install-macos.sh at install.

    The portable Linux/macOS dashboard has to carry every panel for every host,
    so a Mac sees several rows that can never fill. Here the machine is known, so
    a panel is included only when this Mac can answer it:

      * memory / swap use the macOS metric names outright (no `or` fallbacks)
      * hwmon CPU / disk temperature panels are dropped — macOS has no hwmon
      * the NVIDIA row appears only when an NVIDIA GPU was actually detected
        (no NVIDIA driver has existed for macOS since Mojave, so on nearly every
        Mac this row is pure noise)
      * Intel-only thermal-throttling panels appear only on Intel

    Anything still empty is a live fault worth investigating, which is the point.
    """
    g = Layout()

    g.row("Overview")
    g.stat("CPU Busy",
           [('100 - (avg(rate(node_cpu_seconds_total{mode="idle",instance=~"$instance"}[$__rate_interval])) * 100)',
             "cpu")],
           "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT)
    # macOS node_exporter has no MemAvailable/MemTotal: used = active + wired +
    # compressed, against node_memory_total_bytes.
    mac_used = (f'(node_memory_active_bytes{INST} + node_memory_wired_bytes{INST}'
                f' + node_memory_compressed_bytes{INST})')
    g.stat("Memory Used",
           [(f'{mac_used} / node_memory_total_bytes{INST} * 100', "mem")],
           "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("Root FS Used",
           [('(1 - (node_filesystem_avail_bytes{mountpoint="/",fstype="apfs",instance=~"$instance"} '
             '/ node_filesystem_size_bytes{mountpoint="/",instance=~"$instance"})) * 100', "/")],
           "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT,
           desc="The APFS system volume. macOS reports the read-only system "
                "snapshot and the writable data volume separately — see the "
                "Filesystem panel below for both.")
    g.stat("Uptime",
           [(f'node_time_seconds{INST} - node_boot_time_seconds{INST}', "uptime")],
           "s", w=4, thresholds=[{"color": "blue", "value": None}])
    g.stat("Load (1m)", [(f'node_load1{INST}', "load1")], "short", w=4,
           decimals=2, thresholds=[{"color": "green", "value": None}])
    g.stat("CPU Cores",
           [(f'count(count(node_cpu_seconds_total{INST}) by (cpu))', "cores")],
           "short", w=4, thresholds=[{"color": "blue", "value": None}],
           desc="Performance and efficiency cores counted together on Apple Silicon.")

    cpu_section(g)

    g.row("Memory")
    g.ts("Memory Usage",
         [(mac_used, "used (active + wired + compressed)"),
          (f'node_memory_inactive_bytes{INST}', "inactive"),
          (f'node_memory_free_bytes{INST}', "free")], "bytes", minv=0,
         desc="macOS keeps free memory near zero on purpose — inactive pages are "
              "cache it will hand back on demand. Rising 'wired' and swap use are "
              "the pressure signals, not low 'free'.")
    swap_section(g, "macos")

    disk_section(g)
    network_section(g)

    temps_section_macos(g, intel=intel)
    gpu_section_apple(g, title="GPU — Apple / integrated")
    if nvidia:
        gpu_section(g, detected=True)

    which = "Intel" if intel else "Apple Silicon"
    # Same uid as the portable dashboard on purpose: re-running the installer, or
    # switching between the tailored and the portable cut, then *replaces* the
    # dashboard instead of leaving two near-identical ones side by side.
    return dashboard(f"System Overview — macOS ({which})", "lesysbot-node", g)


# =================================================================== Windows
def build_windows(caps: set[str] | None = None) -> dict:
    """windows_exporter dashboard.

    ``caps is None`` builds the portable, committed dashboard. ``scripts/start.ps1``
    instead probes the running exporter and passes what it found:

      nvidia        nvidia-smi is on PATH (so nvidia_gpu_exporter can answer)
      thermalzone   windows_exporter is actually serving
                    windows_thermalzone_temperature_celsius — firmware-dependent,
                    common on laptops and rare on desktops

    Probing the live exporter rather than guessing matters here: whether the
    thermal collector returns anything is a property of the firmware, not of
    Windows, so there is no static rule that gets it right.
    """
    g = Layout()
    inst = '{instance=~"$instance"}'

    g.row("Overview")
    g.stat("CPU Busy",
           [('100 - (avg(rate(windows_cpu_time_total{mode="idle",instance=~"$instance"}[$__rate_interval])) * 100)',
             "cpu")], "percent", w=6, gauge=True, minv=0, maxv=100, thresholds=PCT)
    # windows_exporter versions differ on the total-RAM metric name; `or` covers both.
    win_total = ('(windows_cs_physical_memory_bytes{instance=~"$instance"}'
                 ' or windows_memory_physical_total_bytes{instance=~"$instance"})')
    g.stat("Memory Used",
           [(f'(1 - (windows_memory_available_bytes{{instance=~"$instance"}} / {win_total})) * 100', "mem")],
           "percent", w=6, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("System Disk Used",
           [('(1 - (windows_logical_disk_free_bytes{volume="C:",instance=~"$instance"} '
             '/ windows_logical_disk_size_bytes{volume="C:",instance=~"$instance"})) * 100', "C:")],
           "percent", w=6, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("Uptime",
           [(f'time() - windows_system_system_up_time{inst}', "uptime")], "s", w=6,
           thresholds=[{"color": "blue", "value": None}])

    g.row("CPU")
    g.ts("CPU Usage by Mode",
         [('avg by (mode) (rate(windows_cpu_time_total{mode!="idle",instance=~"$instance"}[$__rate_interval])) * 100',
           "{{mode}}")], "percent", stack=True, minv=0)
    g.ts("CPU Usage Total",
         [('100 - (avg(rate(windows_cpu_time_total{mode="idle",instance=~"$instance"}[$__rate_interval])) * 100)',
           "busy")], "percent", minv=0)

    g.row("Memory")
    g.ts("Memory Usage",
         [(f'{win_total} - windows_memory_available_bytes{inst}', "used"),
          (f'windows_memory_available_bytes{inst}', "available")], "bytes", minv=0)
    g.ts("Memory Committed",
         [(f'windows_memory_committed_bytes{inst}', "committed"),
          (f'windows_memory_commit_limit{inst}', "limit")], "bytes", minv=0, fill=0)

    g.row("Disk")
    g.ts("Logical Disk Used %",
         [('(1 - (windows_logical_disk_free_bytes{instance=~"$instance"} '
           '/ windows_logical_disk_size_bytes{instance=~"$instance"})) * 100',
           "{{volume}}")], "percent", fill=0, minv=0)
    g.ts("Disk I/O",
         [(f'rate(windows_logical_disk_read_bytes_total{inst}[$__rate_interval])', "{{volume}} read"),
          (f'-rate(windows_logical_disk_write_bytes_total{inst}[$__rate_interval])', "{{volume}} write")],
         "Bps")

    g.row("Network — Ethernet & Wifi (per NIC)")
    g.ts("Network Received",
         [(f'rate(windows_net_bytes_received_total{inst}[$__rate_interval]) * 8', "{{nic}}")],
         "bps", minv=0)
    g.ts("Network Sent",
         [(f'rate(windows_net_bytes_sent_total{inst}[$__rate_interval]) * 8', "{{nic}}")],
         "bps", minv=0)

    temps_section_windows(g, caps)
    if caps is None or "nvidia" in caps:
        gpu_section(g, detected=caps is not None)
    title = "System Overview — Windows"
    return dashboard(title, "lesysbot-windows", g)


# Capabilities each --host accepts. Keeping this explicit means a typo in a start
# script is a usage error rather than a silently-missing dashboard row.
CAPABILITIES = {
    "linux": {"nvidia", "amd_gpu", "cpu_temp", "disk_temp", "thermal_zone"},
    "macos": {"intel", "nvidia"},
    "windows": {"nvidia", "thermalzone"},
}


def build_for(host: str, caps: set[str]) -> dict:
    if host == "linux":
        return build_linux(caps)
    if host == "macos":
        return build_macos(intel="intel" in caps, nvidia="nvidia" in caps)
    return build_windows(caps)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="With no --host, rewrites the two committed portable dashboards.")
    ap.add_argument("--host", choices=sorted(CAPABILITIES),
                    help="generate one dashboard tailored to this host instead of "
                         "rewriting the bundled JSONs")
    ap.add_argument("--have", default="",
                    help="comma-separated capabilities the host was probed to have. "
                         + "; ".join(f"{h}: {','.join(sorted(c))}"
                                     for h, c in sorted(CAPABILITIES.items())))
    ap.add_argument("--out", type=Path,
                    help="with --host: file to write (default: stdout)")
    args = ap.parse_args(argv)

    if args.host:
        caps = {c.strip() for c in args.have.split(",") if c.strip()}
        unknown = caps - CAPABILITIES[args.host]
        if unknown:
            ap.error(f"unknown capability for --host {args.host}: "
                     f"{', '.join(sorted(unknown))} "
                     f"(known: {', '.join(sorted(CAPABILITIES[args.host]))})")
        model = build_for(args.host, caps)
        text = json.dumps(model, indent=2) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text)
            print(f"wrote {args.out}  ({len(model['panels'])} panels)")
        else:
            sys.stdout.write(text)
        return

    if args.have or args.out:
        ap.error("--have/--out only apply together with --host")

    OUT.mkdir(parents=True, exist_ok=True)
    for name, model in [
        ("system-overview-linux-macos.json", build_node()),
        ("system-overview-windows.json", build_windows()),
    ]:
        path = OUT / name
        path.write_text(json.dumps(model, indent=2) + "\n")
        print(f"wrote {path}  ({len(model['panels'])} panels)")


if __name__ == "__main__":
    main()
