#!/usr/bin/env python3
"""Generate the bundled Grafana dashboard for the LeSysBot dashboard stack.

This is the source of truth for the JSON under ``dashboard/grafana/dashboards/``.
Editing the JSON by hand is fine for a quick tweak, but prefer changing this file
and re-running it so the dashboard stays consistent:

    python3 dashboard/scripts/gen-dashboards.py

It writes:
  * system-overview.json  — node_exporter + GPU

That one is the *portable* dashboard: a single JSON has to serve every Linux
host, so panels a given machine can't fill are simply empty there. The start
script instead probes the machine it's on and asks for a dashboard cut to it:

    python3 gen-dashboards.py --host linux --have cpu_temp,disk_temp,nvidia --out PATH

Each `--have` capability is something the caller *verified* (an hwmon chip of
that family exists, nvidia-smi answers, the exporter really serves that metric),
and a panel is included only when something can fill it. The point is that an
empty panel then means a fault worth chasing rather than "this machine never had
that sensor" — which is indistinguishable to the person looking at it.

Generating per machine is what keeps this file the single source of truth without
committing a JSON for every hardware combination. `scripts/start.sh` does the
probing; see `CAPABILITIES` below for what it may pass.

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
        "query": {"query": 'label_values(up{job="node"}, instance)',
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
# portable dashboard and the probed host-specific cut. Only the sections whose
# queries are *identical* in both live here; Overview and Memory differ (the cut
# drops fallbacks a portable JSON still needs) and stay per-flavour.
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

    ``flavour`` is "portable" or "linux". Both ask for the same metrics now that
    Linux is the only host; the argument stays so the two builders keep reading
    the same way, and so the description can be blunter on a probed host.
    """
    used = f'node_memory_SwapTotal_bytes{INST} - node_memory_SwapFree_bytes{INST}'
    free = f'node_memory_SwapFree_bytes{INST}'
    desc = "Empty means swap is off (or you're in a container without any)."
    if flavour != "linux":
        desc = ("Empty means swap is off — on this un-probed dashboard that is "
                "indistinguishable from a host that simply has none.")
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
    """CPU / disk / sensor temperatures (hwmon + thermal zones), un-probed.

    This is the portable cut: it asks for every sensor family a Linux box might
    have, and a machine without one leaves that panel empty. ``temps_section_linux``
    covers the same ground for a host whose chips were actually probed.
    """
    g.row("Temperatures — CPU / Disk / Sensors")
    g.stat("CPU Temperature",
           [(_MAX_FOR.format(chips=CPU_CHIPS), "cpu")],
           "celsius", w=8, thresholds=TEMP,
           desc="Hottest hwmon CPU sensor (coretemp / k10temp / cpu_thermal).")
    g.stat("Disk Temperature", [(_MAX_FOR.format(chips=DISK_CHIPS), "disk")], "celsius",
           w=8, thresholds=TEMP,
           desc="NVMe / SATA drive temperature, from the nvme and drivetemp chips.")
    g.stat("GPU Temperature",
           [(f"max({GPU_TEMP})", "gpu")],
           "celsius", w=8, thresholds=TEMP,
           desc="NVIDIA GPUs report this directly through nvidia_gpu_exporter.")
    g.ts("CPU Temperature (package & per-core)",
         [(f'{_LABELED}{{chip_name=~"{CPU_CHIPS}"}}', "{{label}}")], "celsius",
         minv=0, fill=0,
         desc="Package and per-core temperatures (Intel coretemp / AMD k10temp / ARM).")
    g.ts("Disk Temperature",
         [(f'{_LABELED}{{chip_name=~"{DISK_CHIPS}"}}', "{{chip_name}} {{label}}")], "celsius",
         minv=0, fill=0,
         desc="NVMe (nvme) and SATA (drivetemp) drive temperatures.")
    g.ts("Other Sensors — ACPI zone / chipset / Wifi radio",
         [("node_thermal_zone_temp", "{{type}} (zone {{zone}})")], "celsius",
         minv=0, fill=0,
         desc="ACPI thermal zones — CPU package (x86_pkg_temp), chassis (acpitz), "
              "Wifi radio (iwlwifi).")


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


def build_node() -> dict:
    g = Layout()
    inst = '{instance=~"$instance"}'

    g.row("Overview")
    g.stat("CPU Busy",
           [('100 - (avg(rate(node_cpu_seconds_total{mode="idle",instance=~"$instance"}[$__rate_interval])) * 100)',
             "cpu")],
           "percent", w=4, gauge=True, minv=0, maxv=100, thresholds=PCT)
    g.stat("Memory Used",
           [(f'(1 - (node_memory_MemAvailable_bytes{inst} / node_memory_MemTotal_bytes{inst})) * 100',
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
    g.ts("Memory Usage",
         [(f'node_memory_MemTotal_bytes{inst} - node_memory_MemAvailable_bytes{inst}', "used"),
          (f'node_memory_Cached_bytes{inst}', "cached"),
          (f'node_memory_MemAvailable_bytes{inst}', "available")],
         "bytes", minv=0)
    swap_section(g, "portable")

    disk_section(g)
    network_section(g)

    temps_section_node(g)
    gpu_section(g)
    return dashboard("System Overview", "lesysbot-node", g)


# ==================================================== Linux (host-specific cut)
def build_linux(caps: set[str]) -> dict:
    """A dashboard for one Linux host, generated by scripts/start.sh at start-up.

    The bargain: the host was probed, so panels it cannot fill are left out
    rather than rendered blank. What `caps` can hold, and what start.sh probes
    to decide:

      cpu_temp / disk_temp / amd_gpu   an hwmon chip of that family exists
                                       under /sys/class/hwmon/*/name
      thermal_zone                     /sys/class/thermal/thermal_zone* exists
      nvidia                           nvidia-smi is on PATH

    The portable cut's catch-all sensor panels are dropped too — on a probed
    host they only make the queries harder to read.
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


#: What `--have` may name. `scripts/start.sh` probes these; see build_linux().
CAPABILITIES = {
    "linux": {"nvidia", "amd_gpu", "cpu_temp", "disk_temp", "thermal_zone"},
}


def build_for(host: str, caps: set[str]) -> dict:
    assert host == "linux", host        # the only entry in CAPABILITIES
    return build_linux(caps)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="With no --host, rewrites the committed portable dashboard.")
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
    model = build_node()
    path = OUT / "system-overview.json"
    path.write_text(json.dumps(model, indent=2) + "\n")
    print(f"wrote {path}  ({len(model['panels'])} panels)")


if __name__ == "__main__":
    main()
