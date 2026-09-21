"""Tests for dashboard/scripts/gen-dashboards.py.

Like ``test_macos_metrics.py``, the script lives outside the package
(``dashboard/`` is not shipped in the wheel), so it is loaded by path. It is
stdlib-only and pure — no OS calls to stub — so this suite runs anywhere.

The macOS builder is the reason this file exists. ``scripts/install-macos.sh``
detects the hardware and asks for a dashboard cut to it, and the failure mode of
getting that wrong is silent: a panel that queries a metric the host can never
produce renders empty, which is indistinguishable from a broken stack. So each
test below pins one of those inclusion/exclusion decisions.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "dashboard" / "scripts" / "gen-dashboards.py"


def _load():
    spec = importlib.util.spec_from_file_location("gen_dashboards", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gen():
    return _load()


def _exprs(model: dict) -> str:
    """Every PromQL expression in the dashboard, as one searchable blob."""
    return "\n".join(
        t["expr"] for panel in model["panels"] for t in panel.get("targets", []) or []
    )


def _rows(model: dict) -> list[str]:
    return [p["title"] for p in model["panels"] if p["type"] == "row"]


def _titles(model: dict) -> list[str]:
    return [p["title"] for p in model["panels"] if p["type"] != "row"]


# ---------------------------------------------------------------- NVIDIA row
def test_macos_omits_nvidia_unless_detected(gen):
    """The row a Mac can never fill is left out, not provisioned empty.

    No NVIDIA driver has existed for macOS since Mojave, so on virtually every
    Mac this row is permanent noise — and it is the most-reported "my dashboard
    is broken" symptom.
    """
    model = gen.build_macos()
    assert "nvidia_smi" not in _exprs(model)
    assert not any("NVIDIA" in r for r in _rows(model))


def test_macos_includes_nvidia_when_detected(gen):
    model = gen.build_macos(nvidia=True)
    assert "nvidia_smi_utilization_gpu_ratio" in _exprs(model)
    assert any("NVIDIA" in r for r in _rows(model))


# ------------------------------------------------------- Apple Silicon / Intel
def test_intel_only_gets_the_throttling_panels(gen):
    """node_exporter's darwin thermal collector reports throttling, and its
    underlying API is Intel-only — on Apple Silicon it reports failure."""
    intel = gen.build_macos(intel=True)
    apple = gen.build_macos(intel=False)
    assert "node_thermal_cpu_speed_limit_ratio" in _exprs(intel)
    assert "node_thermal" not in _exprs(apple)
    assert "Intel" in intel["title"]
    assert "Apple Silicon" in apple["title"]


def test_macos_drops_linux_only_sensor_panels(gen):
    """hwmon does not exist on macOS, so those panels can only ever be blank."""
    exprs = _exprs(gen.build_macos(intel=True, nvidia=True))
    assert "node_hwmon" not in exprs
    assert not any("Disk Temperature" in t for t in _titles(gen.build_macos()))


def test_macos_uses_macos_metric_names(gen):
    """No Linux `or` fallbacks: on a known host the query names what exists."""
    exprs = _exprs(gen.build_macos())
    assert "node_memory_MemAvailable_bytes" not in exprs
    assert "node_memory_swap_used_bytes" in exprs      # not SwapFree/SwapTotal
    assert "macos_battery_temperature_celsius" in exprs


def test_macos_surfaces_collector_staleness(gen):
    """A .prom file keeps being served after its writer dies, so the dashboard
    has to show the sample's age rather than a plausible frozen value."""
    assert "macos_metrics_last_run_timestamp_seconds" in _exprs(gen.build_macos())


def test_die_temperature_panels_explain_the_missing_helper(gen):
    """Both die-temperature tiles are empty without smctemp/macmon, so each one
    has to say so — an unexplained empty tile reads as a fault."""
    model = gen.build_macos()
    for title in ("CPU Die Temperature", "GPU Die Temperature"):
        panel = next(p for p in model["panels"] if p.get("title") == title)
        assert "macmon" in panel["description"] and "smctemp" in panel["description"]


# ------------------------------------------------------------------ Linux cut
def test_linux_temperature_panels_follow_the_detected_chips(gen):
    """start.sh reads /sys/class/hwmon/*/name; each family it finds should bring
    in its panels and nothing else."""
    cpu_only = _exprs(gen.build_linux({"cpu_temp"}))
    assert CPU_CHIPS_MARKER in cpu_only
    assert "nvme|drivetemp" not in cpu_only
    assert "amdgpu" not in cpu_only

    disk_only = _exprs(gen.build_linux({"disk_temp"}))
    assert "nvme|drivetemp" in disk_only
    assert "coretemp" not in disk_only


def test_linux_without_any_sensor_has_no_temperature_row(gen):
    """A VM or container host has no hwmon at all — an empty Temperatures row is
    worse than none, because it reads as a broken dashboard."""
    model = gen.build_linux(set())
    assert not any("Temperature" in r for r in _rows(model))
    assert not any("GPU" in r for r in _rows(model))


def test_linux_amd_gpu_does_not_imply_the_nvidia_row(gen):
    """amdgpu comes from hwmon and needs no exporter; the NVIDIA row needs one."""
    model = gen.build_linux({"amd_gpu"})
    assert "nvidia_smi" not in _exprs(model)
    assert any("AMD GPU" in t for t in _titles(model))


def test_linux_nvidia_row_drops_the_might_be_missing_caveat(gen):
    """On a tailored cut the row exists only because nvidia-smi answered, so an
    empty row there is a real fault — the portable title would say otherwise."""
    tailored = _rows(gen.build_linux({"nvidia"}))
    assert "GPU — NVIDIA" in tailored
    assert "GPU — NVIDIA (down if no NVIDIA card / exporter)" in _rows(gen.build_node())


def test_linux_cut_drops_the_macos_fallbacks(gen):
    exprs = _exprs(gen.build_linux({"cpu_temp"}))
    assert "node_memory_active_bytes" not in exprs
    assert "node_memory_swap_used_bytes" not in exprs
    assert "node_memory_MemAvailable_bytes" in exprs


# ---------------------------------------------------------------- Windows cut
def test_windows_thermal_row_requires_a_working_sensor(gen):
    """start.ps1 probes the running exporter, because whether thermalzone
    answers is a property of the firmware, not of Windows."""
    without = gen.build_windows(set())
    assert not any("Temperature" in r for r in _rows(without))
    assert "windows_thermalzone" not in _exprs(without)

    with_zone = gen.build_windows({"thermalzone"})
    assert "windows_thermalzone_temperature_celsius" in _exprs(with_zone)


def test_windows_portable_keeps_both_panels(gen):
    """`caps is None` is the committed dashboard, which must stay unconditional."""
    exprs = _exprs(gen.build_windows())
    assert "windows_thermalzone_temperature_celsius" in exprs
    assert "nvidia_smi_temperature_gpu" in exprs


# ------------------------------------------------------------------ all cuts
CPU_CHIPS_MARKER = "coretemp|k10temp|cpu_thermal"

ALL_CUTS = [
    ("macos", caps) for caps in ([], ["intel"], ["nvidia"], ["intel", "nvidia"])
] + [
    ("linux", caps) for caps in ([], ["cpu_temp"], ["disk_temp"], ["amd_gpu"], ["nvidia"],
                                 ["cpu_temp", "disk_temp", "thermal_zone", "nvidia", "amd_gpu"])
] + [
    ("windows", caps) for caps in ([], ["nvidia"], ["thermalzone"], ["nvidia", "thermalzone"])
]


@pytest.mark.parametrize("host,caps", ALL_CUTS)
def test_every_cut_is_valid_grafana_json(gen, host, caps):
    """The start scripts generate one of these; a broken one provisions a
    dashboard Grafana silently refuses to load."""
    model = gen.build_for(host, set(caps))
    json.dumps(model)                                   # serialisable
    # Shared uid per exporter family: re-running a start script replaces the
    # dashboard rather than leaving near-duplicates side by side.
    assert model["uid"] == ("lesysbot-windows" if host == "windows" else "lesysbot-node")
    ids = [p["id"] for p in model["panels"]]
    assert len(ids) == len(set(ids))
    for panel in model["panels"]:
        assert panel["gridPos"]["x"] + panel["gridPos"]["w"] <= 24
        assert panel["gridPos"]["w"] > 0


@pytest.mark.parametrize("host", ["linux", "macos", "windows"])
def test_cli_rejects_capabilities_the_host_cannot_have(gen, host):
    """A typo in a start script must fail loudly, not drop a dashboard row."""
    with pytest.raises(SystemExit):
        gen.main(["--host", host, "--have", "definitely_not_a_capability"])


# ----------------------------------------------------------- portable dashboard
def test_portable_swap_panel_covers_both_operating_systems(gen):
    """macOS names its swap metrics differently from Linux; the portable panel
    has to ask for both or it reads as "Linux only" on a Mac."""
    exprs = _exprs(gen.build_node())
    assert "node_memory_SwapTotal_bytes" in exprs
    assert "node_memory_swap_used_bytes" in exprs


def test_bundled_json_matches_the_generator(gen, tmp_path):
    """The committed JSON is generated output — regenerate rather than hand-edit."""
    out = SCRIPT.resolve().parent.parent / "grafana" / "dashboards"
    for name, model in [("system-overview-linux-macos.json", gen.build_node()),
                        ("system-overview-windows.json", gen.build_windows())]:
        assert json.loads((out / name).read_text()) == model, (
            f"{name} is stale — re-run: python3 dashboard/scripts/gen-dashboards.py"
        )
