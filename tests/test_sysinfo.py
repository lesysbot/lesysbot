"""Tests for the best-effort collectors behind the startup notice
(lesysbot/core/sysinfo.py). Sensor reads run against a fake /sys tree; the
speed test against a fake fetcher — no real hardware or network needed."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from lesysbot.core import sysinfo


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _fake_sys(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    thermal = tmp_path / "thermal"
    hwmon = tmp_path / "hwmon"
    monkeypatch.setattr(sysinfo, "_THERMAL_DIR", thermal)
    monkeypatch.setattr(sysinfo, "_HWMON_DIR", hwmon)
    return thermal, hwmon


# ── cpu_temperature ────────────────────────────────────────────────────────


def test_cpu_temperature_reads_thermal_zone(tmp_path, monkeypatch):
    thermal, _ = _fake_sys(monkeypatch, tmp_path)
    _write(thermal / "thermal_zone0" / "type", "x86_pkg_temp\n")
    _write(thermal / "thermal_zone0" / "temp", "54000\n")
    assert sysinfo.cpu_temperature() == "54°C"


def test_cpu_temperature_prefers_cpu_sensors(tmp_path, monkeypatch):
    thermal, _ = _fake_sys(monkeypatch, tmp_path)
    # A hotter non-CPU zone (e.g. wifi chip) must not win over the CPU zone.
    _write(thermal / "thermal_zone0" / "type", "iwlwifi_1\n")
    _write(thermal / "thermal_zone0" / "temp", "99000\n")
    _write(thermal / "thermal_zone1" / "type", "x86_pkg_temp\n")
    _write(thermal / "thermal_zone1" / "temp", "54000\n")
    assert sysinfo.cpu_temperature() == "54°C"


def test_cpu_temperature_reads_hwmon_and_takes_hottest(tmp_path, monkeypatch):
    _, hwmon = _fake_sys(monkeypatch, tmp_path)
    _write(hwmon / "hwmon0" / "name", "k10temp\n")
    _write(hwmon / "hwmon0" / "temp1_input", "61000\n")
    _write(hwmon / "hwmon0" / "temp2_input", "48000\n")
    assert sysinfo.cpu_temperature() == "61°C"


def test_cpu_temperature_ignores_junk_readings(tmp_path, monkeypatch):
    thermal, _ = _fake_sys(monkeypatch, tmp_path)
    _write(thermal / "thermal_zone0" / "type", "cpu-thermal\n")
    _write(thermal / "thermal_zone0" / "temp", "-273000\n")  # dead sensor
    _write(thermal / "thermal_zone1" / "type", "cpu-thermal\n")
    _write(thermal / "thermal_zone1" / "temp", "not-a-number\n")
    assert sysinfo.cpu_temperature() is None


def test_cpu_temperature_none_without_sensors(tmp_path, monkeypatch):
    _fake_sys(monkeypatch, tmp_path)  # dirs don't even exist
    assert sysinfo.cpu_temperature() is None


# ── gpu_temperature ────────────────────────────────────────────────────────


async def test_gpu_temperature_none_without_nvidia_smi(monkeypatch):
    monkeypatch.setattr(sysinfo.shutil, "which", lambda _: None)
    assert await sysinfo.gpu_temperature() is None


@pytest.mark.skipif(os.name == "nt", reason="fake executable is a shell script")
async def test_gpu_temperature_parses_nvidia_smi(tmp_path, monkeypatch):
    fake = tmp_path / "nvidia-smi"
    fake.write_text("#!/bin/sh\necho '0, 47'\necho '1, 51'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)
    assert await sysinfo.gpu_temperature() == "GPU0: 47°C, GPU1: 51°C"


# ── disk_usage_line ────────────────────────────────────────────────────────


def test_disk_usage_line_reports_free_and_total(tmp_path):
    line = sysinfo.disk_usage_line(str(tmp_path))
    assert line is not None
    assert "GB free of" in line
    assert "% used" in line


def test_disk_usage_line_none_for_missing_path():
    assert sysinfo.disk_usage_line("/no/such/path/anywhere") is None


# ── internet_speed ─────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, size: int) -> None:
        self._left = size

    def read(self, n: int = -1) -> bytes:
        take = self._left if n < 0 else min(self._left, n)
        self._left -= take
        return b"x" * take

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


async def test_internet_speed_reports_mbps_and_latency(monkeypatch):
    def fake_fetch(url: str):
        size = int(parse_qs(urlparse(url).query)["bytes"][0])
        return _FakeResponse(size)

    monkeypatch.setattr(sysinfo, "_fetch", fake_fetch)
    line = await sysinfo.internet_speed(1.0)
    assert line is not None
    assert line.startswith("↓ ")
    assert "Mbps" in line
    assert "ms latency" in line


async def test_internet_speed_none_when_offline(monkeypatch):
    def fake_fetch(url: str):
        raise OSError("network unreachable")

    monkeypatch.setattr(sysinfo, "_fetch", fake_fetch)
    assert await sysinfo.internet_speed(1.0) is None


# ── startup_report ─────────────────────────────────────────────────────────


async def test_startup_report_includes_available_readings(monkeypatch):
    monkeypatch.setattr(sysinfo, "cpu_temperature", lambda: "54°C")
    monkeypatch.setattr(sysinfo, "disk_usage_line", lambda: "/ — 100 GB free of 200 GB (50% used)")
    monkeypatch.setattr(sysinfo, "uptime", lambda: "42s")

    async def fake_gpu():
        return "GPU0: 47°C"

    async def fake_net(size_mb):
        return "↓ 80.0 Mbps, 12 ms latency"

    monkeypatch.setattr(sysinfo, "gpu_temperature", fake_gpu)
    monkeypatch.setattr(sysinfo, "internet_speed", fake_net)

    report = await sysinfo.startup_report()
    assert "LeSysBot is online" in report
    assert "Uptime: 42s" in report
    assert "CPU temp: 54°C" in report
    assert "GPU temp: GPU0: 47°C" in report
    assert "Disk: / — 100 GB free" in report
    assert "Internet: ↓ 80.0 Mbps" in report


async def test_startup_report_omits_unavailable_readings(monkeypatch):
    monkeypatch.setattr(sysinfo, "cpu_temperature", lambda: None)
    monkeypatch.setattr(sysinfo, "disk_usage_line", lambda: None)
    monkeypatch.setattr(sysinfo, "uptime", lambda: None)

    async def fake_gpu():
        return None

    monkeypatch.setattr(sysinfo, "gpu_temperature", fake_gpu)

    report = await sysinfo.startup_report(speedtest_mb=None)
    assert "LeSysBot is online" in report
    assert "CPU temp" not in report
    assert "GPU temp" not in report
    assert "Disk" not in report
    assert "Internet" not in report


async def test_startup_report_flags_failed_speedtest(monkeypatch):
    monkeypatch.setattr(sysinfo, "cpu_temperature", lambda: None)
    monkeypatch.setattr(sysinfo, "disk_usage_line", lambda: None)
    monkeypatch.setattr(sysinfo, "uptime", lambda: None)

    async def fake_gpu():
        return None

    async def fake_net(size_mb):
        return None

    monkeypatch.setattr(sysinfo, "gpu_temperature", fake_gpu)
    monkeypatch.setattr(sysinfo, "internet_speed", fake_net)

    report = await sysinfo.startup_report(speedtest_mb=5.0)
    assert "Internet: speed test failed" in report


def test_format_duration():
    assert sysinfo._format_duration(42) == "42s"
    assert sysinfo._format_duration(150) == "2m 30s"
    assert sysinfo._format_duration(3 * 3600 + 240) == "3h 4m"
    assert sysinfo._format_duration(2 * 86400 + 5 * 3600) == "2d 5h"


# ── uptime (per-OS dispatch) ───────────────────────────────────────────────


def test_uptime_linux_reads_proc(tmp_path, monkeypatch):
    up = tmp_path / "uptime"
    up.write_text("12345.67 8910.11\n")
    monkeypatch.setattr(sysinfo, "_UPTIME_FILE", up)
    monkeypatch.setattr(sysinfo.platform, "system", lambda: "Linux")
    assert sysinfo.uptime() == "3h 25m"


@pytest.mark.skipif(
    os.name == "nt",
    reason="ctypes.windll exists on Windows, so the branch returns a real uptime, not None",
)
def test_uptime_windows_branch_degrades_gracefully(monkeypatch):
    """On a non-Windows host ctypes has no windll — the branch must return None."""
    monkeypatch.setattr(sysinfo.platform, "system", lambda: "Windows")
    assert sysinfo._uptime_seconds() is None


def test_uptime_darwin_parses_boottime(monkeypatch):
    import time

    monkeypatch.setattr(sysinfo.platform, "system", lambda: "Darwin")
    boot = int(time.time()) - 3600
    monkeypatch.setattr(
        sysinfo, "_sysctl_boottime",
        lambda: f"{{ sec = {boot}, usec = 0 }} Sat Jul 19 10:00:00 2026",
    )
    seconds = sysinfo._uptime_seconds()
    assert seconds is not None
    assert 3590 < seconds < 3620


def test_uptime_darwin_none_without_sysctl(monkeypatch):
    monkeypatch.setattr(sysinfo.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(sysinfo, "_sysctl_boottime", lambda: None)
    assert sysinfo._uptime_seconds() is None
