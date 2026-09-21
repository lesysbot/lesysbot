"""Sensor-parsing logic in the bundled `temperature` package — no real hardware.

`_hwmon_readings` and `_zone_readings` take their sysfs root as a parameter, so
these tests build a fake `/sys` tree under tmp_path and assert on the
formatting. The nvidia-smi half needs the binary and is left to a live check.

The package is loaded by file path, not imported: `tools/` is a tools directory
for LeSysBot's loader, not a Python package.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_TOOL_PY = Path(__file__).resolve().parents[1] / "tools" / "temperature" / "tool.py"

spec = importlib.util.spec_from_file_location("_temperature_under_test", _TOOL_PY)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def make_chip(base: Path, index: int, name: str, temps: dict[str, tuple[int, str | None]]) -> None:
    """Write a fake hwmon chip: temps maps tempN -> (millidegrees, label)."""
    chip = base / f"hwmon{index}"
    chip.mkdir(parents=True)
    (chip / "name").write_text(name)
    for key, (millideg, label) in temps.items():
        (chip / f"{key}_input").write_text(str(millideg))
        if label is not None:
            (chip / f"{key}_label").write_text(label)


def test_cpu_chip_reports_package_verbatim_and_cores_as_a_range(tmp_path):
    make_chip(tmp_path, 0, "coretemp", {
        "temp1": (45000, "Package id 0"),
        "temp2": (42000, "Core 0"),
        "temp3": (47000, "Core 1"),
        "temp4": (44000, "Core 2"),
    })
    cpu, gpu = mod._hwmon_readings(tmp_path)
    assert cpu == ["coretemp Package id 0: 45°C", "coretemp 3 cores: 42–47°C"]
    assert gpu == []


def test_unlabelled_reading_falls_back_to_the_chip_name(tmp_path):
    make_chip(tmp_path, 0, "k10temp", {"temp1": (38500, None)})
    cpu, _ = mod._hwmon_readings(tmp_path)
    assert cpu == ["k10temp: 38°C"]


def test_gpu_chip_lands_in_the_gpu_section(tmp_path):
    make_chip(tmp_path, 0, "amdgpu", {"temp1": (52000, "edge")})
    cpu, gpu = mod._hwmon_readings(tmp_path)
    assert cpu == []
    assert gpu == ["amdgpu edge: 52°C"]


def test_ambiguous_chips_are_skipped(tmp_path):
    """acpitz/nvme/wifi could be anything — this tool reports CPU and GPU only."""
    make_chip(tmp_path, 0, "acpitz", {"temp1": (40000, None)})
    make_chip(tmp_path, 1, "nvme", {"temp1": (36000, "Composite")})
    assert mod._hwmon_readings(tmp_path) == ([], [])


def test_unreadable_sensor_is_skipped_not_fatal(tmp_path):
    """Sensors can return garbage or vanish mid-read — skip, don't crash."""
    make_chip(tmp_path, 0, "coretemp", {"temp1": (45000, "Package id 0")})
    (tmp_path / "hwmon0" / "temp2_input").write_text("not a number")
    cpu, _ = mod._hwmon_readings(tmp_path)
    assert cpu == ["coretemp Package id 0: 45°C"]


def test_missing_hwmon_root_gives_no_readings(tmp_path):
    assert mod._hwmon_readings(tmp_path / "nope") == ([], [])


# ── thermal-zone fallback (boards with no hwmon CPU chip) ──────────────────


def make_zone(base: Path, index: int, zone_type: str, millideg: int) -> None:
    zone = base / f"thermal_zone{index}"
    zone.mkdir(parents=True)
    (zone / "type").write_text(zone_type)
    (zone / "temp").write_text(str(millideg))


def test_thermal_zones_report_cpu_sensors(tmp_path):
    make_zone(tmp_path, 0, "x86_pkg_temp", 57000)
    make_zone(tmp_path, 1, "cpu-thermal", 48000)
    assert mod._zone_readings(tmp_path) == [
        "x86_pkg_temp: 57°C",
        "cpu-thermal: 48°C",
    ]


def test_thermal_zones_skip_non_cpu_types(tmp_path):
    """A battery or wifi zone is not a CPU reading."""
    make_zone(tmp_path, 0, "BAT0", 31000)
    make_zone(tmp_path, 1, "iwlwifi_1", 44000)
    assert mod._zone_readings(tmp_path) == []


def test_thermal_zone_with_unreadable_temp_is_skipped(tmp_path):
    make_zone(tmp_path, 0, "x86_pkg_temp", 57000)
    make_zone(tmp_path, 1, "cpu-thermal", 0)
    (tmp_path / "thermal_zone1" / "temp").write_text("disabled")
    assert mod._zone_readings(tmp_path) == ["x86_pkg_temp: 57°C"]


def test_missing_thermal_root_gives_no_readings(tmp_path):
    assert mod._zone_readings(tmp_path / "nope") == []
