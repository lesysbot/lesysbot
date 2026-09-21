"""Best-effort system snapshot for the startup notice.

Collects CPU temperature, GPU temperature, disk usage, and internet speed —
each *if the machine can provide it* — and formats them as a short plain-text
report. Every collector returns ``None`` instead of raising when the reading
isn't available (no sensors, no nvidia-smi, no network), so the report simply
omits what the host can't answer.

This deliberately doesn't call registered tools: the notice must work
regardless of what's in the user's tools dir, and tools only run in response
to user messages. The bundled `temperature`/`speedtest` packages give the same
readings interactively in chat.
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import time
import urllib.request
from pathlib import Path

# Module-level so tests can point them at a fake /sys tree.
_THERMAL_DIR = Path("/sys/class/thermal")
_HWMON_DIR = Path("/sys/class/hwmon")
_UPTIME_FILE = Path("/proc/uptime")

# Sensor names that indicate a CPU reading (thermal zone `type` / hwmon `name`).
_CPU_SENSOR_HINTS = (
    "cpu", "x86_pkg_temp", "coretemp", "k10temp", "zenpower", "soc", "pkg", "acpitz",
)

# Cloudflare's public speed-test endpoint — same approach as tools/speedtest,
# but sized for a quick boot-time check rather than an accurate benchmark.
_SPEED_URL = "https://speed.cloudflare.com/__down?bytes={bytes}"
# Cloudflare 403s the default "Python-urllib/x.y" User-Agent.
_SPEED_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeSysBot/1.0; +startup-notice)"}
_SPEED_TIMEOUT = 15.0  # seconds per HTTP request


def _read_millideg(path: Path) -> float | None:
    try:
        value = int(path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None
    # Dead/disconnected sensors report absurd values (-273, 6553.5, …).
    return value if -20.0 < value < 150.0 else None


def cpu_temperature() -> str | None:
    """Hottest CPU sensor reading, e.g. ``"54°C"``, or None if unavailable.

    Reads thermal zones and hwmon devices under /sys; a host whose kernel or
    hardware exposes neither reports None.
    """
    readings: list[tuple[str, float]] = []
    for zone in sorted(_THERMAL_DIR.glob("thermal_zone*")):
        try:
            name = (zone / "type").read_text().strip().lower()
        except OSError:
            continue
        temp = _read_millideg(zone / "temp")
        if temp is not None:
            readings.append((name, temp))
    for hwmon in sorted(_HWMON_DIR.glob("hwmon*")):
        try:
            name = (hwmon / "name").read_text().strip().lower()
        except OSError:
            continue
        for temp_file in sorted(hwmon.glob("temp*_input")):
            temp = _read_millideg(temp_file)
            if temp is not None:
                readings.append((name, temp))
    if not readings:
        return None
    cpu_ish = [t for name, t in readings if any(h in name for h in _CPU_SENSOR_HINTS)]
    hottest = max(cpu_ish or [t for _, t in readings])
    return f"{hottest:.0f}°C"


async def gpu_temperature() -> str | None:
    """NVIDIA GPU temperature(s) via nvidia-smi, or None without one."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=index,temperature.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        return None
    readings = []
    for line in stdout.decode().splitlines():
        index, _, temp = line.strip().partition(",")
        if temp.strip():
            readings.append(f"GPU{index.strip()}: {temp.strip()}°C")
    return ", ".join(readings) or None


def disk_usage_line(path: str | None = None) -> str | None:
    """Main-drive usage, e.g. ``"/ — 213 GB free of 512 GB (58% used)"``."""
    target = path or Path.home().anchor or "/"
    try:
        usage = shutil.disk_usage(target)
    except OSError:
        return None
    if not usage.total:
        return None
    used_pct = usage.used / usage.total * 100
    return (
        f"{target} — {usage.free / 1e9:.0f} GB free of {usage.total / 1e9:.0f} GB "
        f"({used_pct:.0f}% used)"
    )


def _fetch(url: str):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=_SPEED_HEADERS), timeout=_SPEED_TIMEOUT
    )


def _measure_internet(size_mb: float) -> str | None:
    # Latency: best of three zero-byte round trips.
    latency_ms: float | None = None
    for _ in range(3):
        try:
            start = time.perf_counter()
            with _fetch(_SPEED_URL.format(bytes=0)) as resp:
                resp.read()
            elapsed = (time.perf_counter() - start) * 1000
        except OSError:
            continue
        if latency_ms is None or elapsed < latency_ms:
            latency_ms = elapsed

    try:
        start = time.perf_counter()
        downloaded = 0
        with _fetch(_SPEED_URL.format(bytes=max(1, int(size_mb * 1_000_000)))) as resp:
            while chunk := resp.read(64 * 1024):
                downloaded += len(chunk)
        seconds = time.perf_counter() - start
    except OSError:
        return None
    if seconds <= 0:
        return None
    mbps = downloaded * 8 / seconds / 1_000_000
    line = f"↓ {mbps:.1f} Mbps"
    if latency_ms is not None:
        line += f", {latency_ms:.0f} ms latency"
    return line


async def internet_speed(size_mb: float = 5.0) -> str | None:
    """Download speed + latency via speed.cloudflare.com, or None when offline.

    The urllib calls are blocking, so they run in a worker thread.
    """
    return await asyncio.to_thread(_measure_internet, size_mb)


def _format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _uptime_seconds() -> float | None:
    try:
        return float(_UPTIME_FILE.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def uptime() -> str | None:
    """How long the machine has been up (from /proc/uptime), or None."""
    seconds = _uptime_seconds()
    return _format_duration(seconds) if seconds is not None else None


async def startup_report(speedtest_mb: float | None = 5.0) -> str:
    """Compose the wake-up notice: a header plus whatever the host can report.

    ``speedtest_mb`` is how many MB the speed test downloads; None skips it.
    """
    gpu_coro = gpu_temperature()
    if speedtest_mb:
        gpu, net = await asyncio.gather(gpu_coro, internet_speed(speedtest_mb))
    else:
        gpu, net = await gpu_coro, None

    lines = ["🟢 LeSysBot is online — the system just started."]
    lines.append(
        f"Host: {platform.node() or 'unknown'} ({platform.system()} {platform.release()})"
    )
    up = uptime()
    if up:
        lines.append(f"Uptime: {up}")
    cpu = cpu_temperature()
    if cpu:
        lines.append(f"CPU temp: {cpu}")
    if gpu:
        lines.append(f"GPU temp: {gpu}")
    disk = disk_usage_line()
    if disk:
        lines.append(f"Disk: {disk}")
    if net:
        lines.append(f"Internet: {net}")
    elif speedtest_mb:
        lines.append("Internet: speed test failed — network may still be coming up.")
    return "\n".join(lines)
