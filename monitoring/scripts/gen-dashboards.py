#!/usr/bin/env python3
"""Generate the bundled Grafana dashboards for the LeSysBot monitoring stack.

This is the source of truth for the JSON under ``monitoring/grafana/dashboards/``.
Editing the JSON by hand is fine for a quick tweak, but prefer changing this file
and re-running it so the two dashboards stay consistent:

    python3 monitoring/scripts/gen-dashboards.py

It writes:
  * system-overview-linux-macos.json  — node_exporter    (Linux / macOS)  + GPU
  * system-overview-windows.json      — windows_exporter  (Windows)        + GPU

Every panel binds to the provisioned Prometheus datasource (uid "prometheus").
No third-party libraries — stdlib only.
"""
from __future__ import annotations

import json
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
_LABELED = ("node_hwmon_temp_celsius"
            " * on(chip,sensor) group_left(label) node_hwmon_sensor_label"
            " * on(chip) group_left(chip_name) node_hwmon_chip_names")
_MAX_FOR = ("max(node_hwmon_temp_celsius"
            " * on(chip) group_left(chip_name) node_hwmon_chip_names{{chip_name=~\"{chips}\"}})")


def temps_section_node(g: Layout) -> None:
    """CPU / disk / sensor temperatures (Linux hwmon + thermal zones)."""
    g.row("Temperatures — CPU / Disk / Sensors  (Linux sensors; empty on macOS)")
    g.stat("CPU Temperature", [(_MAX_FOR.format(chips=CPU_CHIPS), "cpu")], "celsius",
           w=8, thresholds=TEMP)
    g.stat("Disk Temperature", [(_MAX_FOR.format(chips=DISK_CHIPS), "disk")], "celsius",
           w=8, thresholds=TEMP)
    g.stat("GPU Temperature", [(f"max({GPU_TEMP})", "gpu")], "celsius", w=8, thresholds=TEMP)
    g.ts("CPU Temperature (package & per-core)",
         [(f'{_LABELED}{{chip_name=~"{CPU_CHIPS}"}}', "{{label}}")], "celsius",
         minv=0, fill=0,
         desc="Package and per-core temperatures (Intel coretemp / AMD k10temp / ARM). Linux only.")
    g.ts("Disk Temperature",
         [(f'{_LABELED}{{chip_name=~"{DISK_CHIPS}"}}', "{{chip_name}} {{label}}")], "celsius",
         minv=0, fill=0,
         desc="NVMe (nvme) and SATA (drivetemp) drive temperatures. Linux only.")
    g.ts("Other Sensors — ACPI zone / chipset / Wifi radio",
         [("node_thermal_zone_temp", "{{type}} (zone {{zone}})")], "celsius",
         minv=0, fill=0,
         desc="ACPI thermal zones: CPU package (x86_pkg_temp), chassis (acpitz), "
              "Wifi radio (iwlwifi), etc. Linux only.")


def temps_section_windows(g: Layout) -> None:
    """Best-effort temperatures on Windows (ACPI thermal zones + GPU)."""
    g.row("Temperatures  (best-effort — ACPI thermalzone; often empty on desktops)")
    g.stat("GPU Temperature", [(f"max({GPU_TEMP})", "gpu")], "celsius", w=12, thresholds=TEMP)
    g.stat("ACPI Zone (max)", [("max(windows_thermalzone_temperature_celsius)", "zone")],
           "celsius", w=12, thresholds=TEMP)
    g.ts("ACPI Thermal Zones",
         [("windows_thermalzone_temperature_celsius", "{{name}}")], "celsius",
         minv=0, fill=0,
         desc="windows_exporter thermalzone collector. Many desktops expose nothing here; "
              "laptops usually do. Per-component CPU/disk temps on Windows need a tool like "
              "LibreHardwareMonitor.")


def gpu_section(g: Layout) -> None:
    """GPU panels — identical on every OS (nvidia_gpu_exporter is cross-platform)."""
    g.row("GPU — NVIDIA (down if no NVIDIA card / exporter)")
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

    g.row("CPU & Load")
    g.ts("CPU Usage by Mode",
         [(f'avg by (mode) (rate(node_cpu_seconds_total{{mode!="idle",instance=~"$instance"}}[$__rate_interval])) * 100',
           "{{mode}}")], "percent", stack=True, minv=0)
    g.ts("Load Average",
         [(f'node_load1{inst}', "1m"), (f'node_load5{inst}', "5m"),
          (f'node_load15{inst}', "15m")], "short", fill=0, minv=0)

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
    g.ts("Swap Usage",
         [(f'node_memory_SwapTotal_bytes{inst} - node_memory_SwapFree_bytes{inst}', "used (Linux)"),
          (f'node_memory_SwapFree_bytes{inst}', "free (Linux)")], "bytes", minv=0,
         desc="Linux swap. macOS reports swap differently (swapped-in/out counters) and is not shown here.")

    g.row("Disk")
    g.ts("Filesystem Used %",
         [('(1 - (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs|devtmpfs",instance=~"$instance"} '
           '/ node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs|devtmpfs",instance=~"$instance"})) * 100',
           "{{mountpoint}}")], "percent", fill=0, minv=0)
    g.ts("Disk I/O",
         [(f'rate(node_disk_read_bytes_total{inst}[$__rate_interval])', "{{device}} read"),
          (f'-rate(node_disk_written_bytes_total{inst}[$__rate_interval])', "{{device}} write")],
         "Bps")

    g.row("Network — Ethernet & Wifi (per interface)")
    g.ts("Network Received",
         [(f'rate(node_network_receive_bytes_total{{{NODE_NIC},instance=~"$instance"}}[$__rate_interval]) * 8',
           "{{device}}")], "bps", minv=0)
    g.ts("Network Transmitted",
         [(f'rate(node_network_transmit_bytes_total{{{NODE_NIC},instance=~"$instance"}}[$__rate_interval]) * 8',
           "{{device}}")], "bps", minv=0)

    temps_section_node(g)
    gpu_section(g)
    return dashboard("System Overview — Linux / macOS", "lesysbot-node", g)


# =================================================================== Windows
def build_windows() -> dict:
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

    temps_section_windows(g)
    gpu_section(g)
    return dashboard("System Overview — Windows", "lesysbot-windows", g)


def main() -> None:
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
