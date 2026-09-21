"""CPU & GPU temperature — kernel sensors plus nvidia-smi.

CPU (and AMD/Intel/nouveau GPU) temperatures come straight from the kernel's
hwmon interface (``/sys/class/hwmon``), so no external binary or pip dependency
is needed. NVIDIA's proprietary driver doesn't expose temperatures through
hwmon, so ``nvidia-smi`` is queried too when it's on PATH.

Boards that publish a CPU sensor only as a **thermal zone** and not as an hwmon
chip (common on ARM SBCs) are covered by a ``/sys/class/thermal`` fallback,
consulted only when hwmon turned up no CPU reading — otherwise the same sensor
would be reported twice under different names.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from lesysbot.mcp import tool

# hwmon driver names → which section a reading belongs to. Ambiguous chips
# (acpitz, nvme, wifi, …) are skipped — this tool reports CPU and GPU only.
_CPU_DRIVERS = {"coretemp", "k10temp", "zenpower", "cpu_thermal"}
_GPU_DRIVERS = {"amdgpu", "radeon", "nouveau", "i915", "xe"}

# Thermal-zone `type` values that mean "this is the CPU". Only consulted when
# hwmon yielded no CPU reading at all.
_CPU_ZONE_TYPES = ("cpu", "x86_pkg_temp", "soc", "pkg")


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _chip_readings(chip: Path, name: str) -> list[tuple[str | None, float]]:
    """All (label, °C) readings of one hwmon chip."""
    readings: list[tuple[str | None, float]] = []
    for input_file in sorted(chip.glob("temp*_input")):
        raw = _read(input_file)
        if raw is None:
            continue
        try:
            degrees = int(raw) / 1000
        except ValueError:
            continue
        label = _read(input_file.with_name(input_file.name.replace("_input", "_label")))
        readings.append((label, degrees))
    return readings


def _cpu_lines(name: str, readings: list[tuple[str | None, float]]) -> list[str]:
    """Chip-level readings (Package/Tctl/…) verbatim; per-core temps as one range."""
    cores = [d for label, d in readings if label and label.lower().startswith("core")]
    lines = [
        f"{name} {label}: {d:.0f}°C" if label else f"{name}: {d:.0f}°C"
        for label, d in readings
        if not (label and label.lower().startswith("core"))
    ]
    if cores:
        lines.append(f"{name} {len(cores)} cores: {min(cores):.0f}–{max(cores):.0f}°C")
    return lines


def _hwmon_readings(base: Path = Path("/sys/class/hwmon")) -> tuple[list[str], list[str]]:
    """Collect (cpu_lines, gpu_lines) from every known hwmon chip under ``base``."""
    cpu: list[str] = []
    gpu: list[str] = []
    for chip in sorted(base.glob("hwmon*")):
        name = _read(chip / "name") or chip.name
        if name in _CPU_DRIVERS:
            cpu += _cpu_lines(name, _chip_readings(chip, name))
        elif name in _GPU_DRIVERS:
            gpu += [
                f"{name} {label}: {d:.0f}°C" if label else f"{name}: {d:.0f}°C"
                for label, d in _chip_readings(chip, name)
            ]
    return cpu, gpu


def _zone_readings(base: Path = Path("/sys/class/thermal")) -> list[str]:
    """CPU lines from thermal zones — the fallback for boards without hwmon."""
    lines: list[str] = []
    for zone in sorted(base.glob("thermal_zone*")):
        zone_type = (_read(zone / "type") or "").strip()
        if not any(hint in zone_type.lower() for hint in _CPU_ZONE_TYPES):
            continue
        raw = _read(zone / "temp")
        if raw is None:
            continue
        try:
            degrees = int(raw) / 1000
        except ValueError:
            continue
        lines.append(f"{zone_type}: {degrees:.0f}°C")
    return lines


async def _nvidia_readings() -> list[str]:
    """GPU temps from nvidia-smi, or [] when it's absent or failing."""
    if shutil.which("nvidia-smi") is None:
        return []
    proc = await asyncio.create_subprocess_exec(
        "nvidia-smi",
        "--query-gpu=index,name,temperature.gpu",
        "--format=csv,noheader,nounits",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return []
    readings = []
    for line in stdout.decode().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        index, temp = parts[0], parts[-1]
        gpu_name = ", ".join(parts[1:-1])
        readings.append(f"GPU{index} {gpu_name}: {temp}°C")
    return readings


@tool(description="Report current CPU and GPU temperatures in °C")
async def temperature() -> str:
    """Return CPU and GPU temperature readings, grouped per device."""
    cpu, gpu = await asyncio.to_thread(_hwmon_readings)
    if not cpu:
        cpu = await asyncio.to_thread(_zone_readings)
    gpu += await _nvidia_readings()

    if not cpu and not gpu:
        return (
            "No temperature sensors found — no supported chip under "
            "/sys/class/hwmon, no CPU thermal zone, and no nvidia-smi on PATH. "
            "Loading sensor kernel modules (e.g. with lm-sensors' "
            "`sensors-detect`) may help."
        )

    def section(title: str, lines: list[str]) -> str:
        if not lines:
            return f"{title}: no sensor found"
        return f"{title}:\n" + "\n".join(f"  {line}" for line in lines)

    return section("CPU", cpu) + "\n" + section("GPU", gpu)
