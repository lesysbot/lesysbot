#!/usr/bin/env python3
"""Export the macOS metrics node_exporter can't reach, as a textfile collector.

`node_exporter` on macOS has no GPU support at all, and its `thermal` collector
reads an Intel-only sysctl (`machdep.xcpm.*`) — on Apple Silicon it just reports
`node_scrape_collector_success{collector="thermal"} 0`. So the temperature and
GPU rows of the dashboard are empty on a Mac no matter how the stack is started.

This fills the gap using only what macOS publishes **without sudo**:

  * **GPU** — `ioreg -c IOAccelerator` carries a `PerformanceStatistics` dict with
    device/renderer/tiler utilization and memory. Present on Apple Silicon and on
    Intel Macs with an integrated/discrete GPU.
  * **Battery temperature** — `ioreg -c AppleSmartBattery`. On a laptop this is
    the one real thermal reading available unprivileged; it tracks chassis heat,
    not the CPU die.

CPU/GPU **die** temperatures are deliberately *not* read here. On Apple Silicon
they come from IOReport (a private framework) or `powermetrics`, which needs
root — and this project never asks for sudo (see docs/writing-tools.md). If you
install a helper that exposes them unprivileged, this script picks it up:

    brew install narugit/tap/smctemp     # CPU + GPU die temperature
    brew install vladkens/tap/macmon     # CPU + GPU die temperature, power

Output goes to a `.prom` file that node_exporter's textfile collector serves.
Written atomically (tmp + rename) because node_exporter may read it mid-write.

    macos-metrics.py <output-dir>        # writes <output-dir>/macos.prom
    macos-metrics.py --stdout            # print instead, for debugging
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

TIMEOUT = 10          # ioreg is normally instant; never hang the launchd job
FILENAME = "macos.prom"


def _run(cmd: list[str]) -> str:
    """Best-effort command output; '' when the tool is missing or fails."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


class Metrics:
    """Accumulates Prometheus text-format samples."""

    def __init__(self) -> None:
        self._out: list[str] = []
        self._declared: set[str] = set()

    def add(self, name: str, value: float, help_: str, labels: dict | None = None,
            type_: str = "gauge") -> None:
        if name not in self._declared:
            self._out.append(f"# HELP {name} {help_}")
            self._out.append(f"# TYPE {name} {type_}")
            self._declared.add(name)
        tags = ""
        if labels:
            inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            tags = "{" + inner + "}"
        # repr(), not %g: %g rounds to 6 significant digits, which silently
        # mangles a Unix timestamp (1785600000 -> 1.7856e+09, off by ~hours) and
        # byte counts. repr round-trips the float exactly.
        self._out.append(f"{name}{tags} {float(value)!r}")

    def render(self) -> str:
        return "\n".join(self._out) + "\n"


# ── GPU (ioreg -c IOAccelerator) ──────────────────────────────────────────────
# The dict is printed on one line as:
#   "PerformanceStatistics" = {"Device Utilization %"=44,"Alloc system memory"=...}
_PERF_RE = re.compile(r'"PerformanceStatistics"\s*=\s*\{(.*?)\}')
_PAIR_RE = re.compile(r'"([^"]+)"=(\d+)')

# ioreg key -> (metric name, label value, divisor). Utilization is reported as a
# whole percent; the dashboards use a 0..1 ratio like nvidia_gpu_exporter does.
_GPU_UTIL = {
    "Device Utilization %": "device",
    "Renderer Utilization %": "renderer",
    "Tiler Utilization %": "tiler",
}
_GPU_MEM = {
    "In use system memory": "in_use",
    "Alloc system memory": "allocated",
}


def collect_gpu(m: Metrics) -> bool:
    out = _run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"])
    if not out:
        return False
    found = False
    for block in _PERF_RE.findall(out):
        stats = {k: int(v) for k, v in _PAIR_RE.findall(block)}
        for key, engine in _GPU_UTIL.items():
            if key in stats:
                m.add("macos_gpu_utilization_ratio", stats[key] / 100.0,
                      "GPU utilization (0-1), from IOAccelerator PerformanceStatistics.",
                      {"engine": engine})
                found = True
        for key, kind in _GPU_MEM.items():
            if key in stats:
                m.add("macos_gpu_memory_bytes", float(stats[key]),
                      "GPU system memory, from IOAccelerator PerformanceStatistics.",
                      {"kind": kind})
                found = True
        if found:
            break        # first accelerator only; Macs have exactly one
    return found


# ── Battery temperature (ioreg -c AppleSmartBattery) ──────────────────────────
# "Temperature" = 3139  -> 31.39 °C (hundredths of a degree).
_BATT_RE = re.compile(r'"Temperature"\s*=\s*(\d+)')


def collect_battery_temp(m: Metrics) -> bool:
    out = _run(["ioreg", "-r", "-w0", "-c", "AppleSmartBattery"])
    match = _BATT_RE.search(out) if out else None
    if not match:
        return False                     # desktop Mac: no battery, no reading
    celsius = int(match.group(1)) / 100.0
    if not 0 < celsius < 100:            # guard against a unit change on new HW
        return False
    m.add("macos_battery_temperature_celsius", celsius,
          "Battery temperature from AppleSmartBattery. Tracks chassis heat, "
          "not the CPU die.")
    return True


# ── Optional die temperatures (only if a sudo-less helper is installed) ───────
_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _first_number(text: str) -> float | None:
    match = _NUM_RE.search(text or "")
    return float(match.group(1)) if match else None


def _plausible(value: object) -> bool:
    """A number that could be a die temperature in °C."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and 0 < float(value) < 130


def _find_temps(node: object, path: str = "") -> dict[str, float]:
    """Walk arbitrary JSON for CPU/GPU temperature fields.

    Deliberately shape-agnostic: it matches on key *names* anywhere in the tree
    rather than a fixed schema. macmon's JSON layout is not part of any stable
    contract and has changed between releases, so pinning to `temp.cpu_temp_avg`
    (or whatever this version calls it) would silently stop working on upgrade —
    and the failure mode is an empty panel nobody notices.
    """
    out: dict[str, float] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}".lower()
            if isinstance(value, (dict, list)):
                out.update(_find_temps(value, here))
            elif "temp" in here and _plausible(value):
                which = "cpu" if "cpu" in here else "gpu" if "gpu" in here else ""
                if which and which not in out:
                    out[which] = float(value)
    elif isinstance(node, list):
        for item in node:
            out.update(_find_temps(item, path))
    return out


def collect_die_temps(m: Metrics) -> bool:
    """smctemp if present, else macmon. Both read the SMC/IOReport without root.

    Neither is installed by us: both live in personal Homebrew taps rather than
    homebrew-core, and a tap can fail on a perfectly ordinary machine (an older
    Xcode is enough to block one). So this is strictly opportunistic — when
    neither is present the CPU/GPU temperature tiles stay empty, which is the
    documented macOS baseline, not a fault.
    """
    found = False
    for flag, name in (("-c", "cpu"), ("-g", "gpu")):
        value = _first_number(_run(["smctemp", flag]))
        if value is not None and _plausible(value):
            m.add(f"macos_{name}_temperature_celsius", value,
                  f"{name.upper()} die temperature (smctemp).")
            found = True
    if found:
        return True

    raw = _run(["macmon", "pipe", "-s", "1"])
    if not raw:
        return False
    import json
    for line in raw.splitlines():          # one JSON object per sample
        line = line.strip()
        if not line:
            continue
        try:
            sample = json.loads(line)
        except ValueError:
            continue
        for which, value in _find_temps(sample).items():
            m.add(f"macos_{which}_temperature_celsius", value,
                  f"{which.upper()} die temperature (macmon).")
            found = True
        if found:
            break
    return found


def build() -> str:
    m = Metrics()
    gpu = collect_gpu(m)
    battery = collect_battery_temp(m)
    die = collect_die_temps(m)
    # A textfile stays on disk (and keeps being served) long after the collector
    # dies, so publish when it last ran — a frozen dashboard is otherwise
    # indistinguishable from an idle machine.
    m.add("macos_metrics_last_run_timestamp_seconds", time.time(),
          "Unix time this collector last wrote its metrics.")
    for source, ok in (("gpu", gpu), ("battery", battery), ("die_temp", die)):
        m.add("macos_metrics_source_up", float(ok),
              "1 when this source answered. die_temp is 0 unless smctemp or "
              "macmon is installed; battery is 0 on a desktop Mac.",
              {"source": source})
    return m.render()


def main(argv: list[str]) -> int:
    text = build()
    if "--stdout" in argv or not argv[1:]:
        sys.stdout.write(text)
        return 0

    out_dir = Path(argv[1])
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # Same directory, so the rename is atomic — node_exporter never sees a
        # half-written file, and a crash can't leave a truncated one in place.
        tmp = out_dir / f".{FILENAME}.{os.getpid()}"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(out_dir / FILENAME)
    except OSError as exc:
        print(f"macos-metrics: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
