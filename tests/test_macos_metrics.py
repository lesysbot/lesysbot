"""Tests for dashboard/scripts/macos-metrics.py.

The script lives outside the package (the stack dir is not shipped in the wheel),
so it's loaded by path. It's stdlib-only and every OS call goes through `_run`,
which the tests replace — so this suite runs on Linux CI just as well as on a Mac.

The die-temperature parsing is the reason this file exists: `smctemp` and
`macmon` can't be installed on every machine (both are personal Homebrew taps,
and an outdated Xcode blocks them), so the parsing has to be verified against
recorded shapes rather than a live tool.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "dashboard" / "scripts" / "macos-metrics.py"


def _load():
    spec = importlib.util.spec_from_file_location("macos_metrics", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mm():
    return _load()


# Real `ioreg -c IOAccelerator` output, trimmed to the line that matters.
IOACCEL = (
    '  +-o IOAccelerator  <class AGXAccelerator>\n'
    '      "PerformanceStatistics" = {"In use system memory (driver)"=0,'
    '"Alloc system memory"=1300889600,"Tiler Utilization %"=32,"recoveryCount"=0,'
    '"Renderer Utilization %"=31,"Device Utilization %"=44,'
    '"In use system memory"=279478272}\n'
)
BATTERY = '      "Temperature" = 3139\n      "VirtualTemperature" = 4069\n'


def test_gpu_and_battery_parsed_from_ioreg(mm, monkeypatch):
    def fake_run(cmd):
        return IOACCEL if "IOAccelerator" in cmd else BATTERY
    monkeypatch.setattr(mm, "_run", fake_run)

    text = mm.build()
    assert 'macos_gpu_utilization_ratio{engine="device"} 0.44' in text
    assert 'macos_gpu_utilization_ratio{engine="renderer"} 0.31' in text
    assert 'macos_gpu_memory_bytes{kind="in_use"} 279478272.0' in text
    assert "macos_battery_temperature_celsius 31.39" in text     # 3139 -> °C
    assert 'macos_metrics_source_up{source="gpu"} 1.0' in text
    assert 'macos_metrics_source_up{source="battery"} 1.0' in text


def test_no_sources_still_emits_a_valid_scrape(mm, monkeypatch):
    """A Mac with nothing readable must produce parseable output, not an error —
    node_exporter refuses to serve a textfile it can't parse, which would take
    every other host metric down with it."""
    monkeypatch.setattr(mm, "_run", lambda cmd: "")
    text = mm.build()
    assert 'macos_metrics_source_up{source="gpu"} 0.0' in text
    assert 'macos_metrics_source_up{source="battery"} 0.0' in text
    for line in text.splitlines():
        if line and not line.startswith("#"):
            float(line.rsplit(" ", 1)[1])        # raises if the value isn't a number


def test_timestamp_keeps_full_precision(mm, monkeypatch):
    """%g would round a Unix timestamp to 6 significant digits (1.7856e+09),
    losing hours and making the staleness check meaningless."""
    monkeypatch.setattr(mm, "_run", lambda cmd: "")
    monkeypatch.setattr(mm.time, "time", lambda: 1785602856.193876)
    line = [row for row in mm.build().splitlines()
            if row.startswith("macos_metrics_last_run")][0]
    assert float(line.split()[1]) == pytest.approx(1785602856.193876, abs=1e-6)


def test_battery_reading_in_unexpected_units_is_dropped(mm, monkeypatch):
    """Guards against a future Mac reporting deci-Kelvin or similar: a bogus
    temperature on the dashboard is worse than an empty panel."""
    monkeypatch.setattr(mm, "_run",
                        lambda cmd: '"Temperature" = 29315\n' if "Battery" in " ".join(cmd) else "")
    assert 'macos_battery_temperature_celsius' not in mm.build()


# ── die temperatures: shape-agnostic macmon parsing ──────────────────────────
@pytest.mark.parametrize("sample", [
    '{"temp": {"cpu_temp_avg": 45.5, "gpu_temp_avg": 38.0}}',
    '{"cpu_temp_c": 45.5, "gpu_temp_c": 38.0}',
    '{"metrics": [{"name": "x"}, {"temp": {"CPU Temperature": 45.5}}], '
    '"gpu": {"temperature": 38.0}}',
])
def test_macmon_temps_found_regardless_of_layout(mm, monkeypatch, sample):
    """macmon's JSON layout isn't a stable contract, so the walk matches on key
    names anywhere in the tree instead of a fixed path."""
    monkeypatch.setattr(mm, "_run",
                        lambda cmd: sample if cmd[0] == "macmon" else "")
    text = mm.build()
    assert "macos_cpu_temperature_celsius 45.5" in text
    assert "macos_gpu_temperature_celsius 38.0" in text
    assert 'macos_metrics_source_up{source="die_temp"} 1.0' in text


def test_macmon_ignores_non_temperature_numbers(mm, monkeypatch):
    """Power draw and utilization sit next to the temperatures; keying on
    'temp' in the path is what keeps 12.5 W out of the temperature panel."""
    monkeypatch.setattr(mm, "_run", lambda cmd: (
        '{"cpu_power_w": 12.5, "gpu_usage": 44, "temp": {"cpu_temp_avg": 45.5}}'
        if cmd[0] == "macmon" else ""))
    text = mm.build()
    assert "macos_cpu_temperature_celsius 45.5" in text
    assert "macos_gpu_temperature_celsius" not in text     # no GPU temp present


def test_smctemp_wins_when_both_installed(mm, monkeypatch):
    def fake_run(cmd):
        if cmd[0] == "smctemp":
            return "45.6\n" if cmd[1] == "-c" else "38.1\n"
        if cmd[0] == "macmon":
            return '{"temp": {"cpu_temp_avg": 99.9}}'
        return ""
    monkeypatch.setattr(mm, "_run", fake_run)
    text = mm.build()
    assert "macos_cpu_temperature_celsius 45.6" in text
    assert "99.9" not in text


def test_absurd_smctemp_reading_rejected(mm, monkeypatch):
    """smctemp reports 0.0 when it can't read the sensor (a common Apple Silicon
    case); publishing that would draw a flat 0 °C line as if it were real."""
    monkeypatch.setattr(mm, "_run",
                        lambda cmd: "0.0\n" if cmd[0] == "smctemp" else "")
    text = mm.build()
    assert "macos_cpu_temperature_celsius" not in text
    assert 'macos_metrics_source_up{source="die_temp"} 0.0' in text
