"""Tests for dashboard/scripts/gen-dashboards.py.

The script lives outside the package (``dashboard/`` is shipped as data, not as
a module), so it is loaded by path. It is stdlib-only and pure — no OS calls to
stub — so this suite runs anywhere.

The host-specific cut is the reason this file exists. ``scripts/start.sh``
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


def test_linux_cut_keeps_the_kernel_memory_metrics(gen):
    exprs = _exprs(gen.build_linux({"cpu_temp"}))
    assert "node_memory_MemAvailable_bytes" in exprs
    assert "node_memory_SwapFree_bytes" in exprs


# ------------------------------------------------------------------ all cuts
CPU_CHIPS_MARKER = "coretemp|k10temp|cpu_thermal"

ALL_CUTS = [
    ("linux", caps) for caps in ([], ["cpu_temp"], ["disk_temp"], ["amd_gpu"], ["nvidia"],
                                 ["cpu_temp", "disk_temp", "thermal_zone", "nvidia", "amd_gpu"])
]


@pytest.mark.parametrize("host,caps", ALL_CUTS)
def test_every_cut_is_valid_grafana_json(gen, host, caps):
    """The start scripts generate one of these; a broken one provisions a
    dashboard Grafana silently refuses to load."""
    model = gen.build_for(host, set(caps))
    json.dumps(model)                                   # serialisable
    # One shared uid: re-running the start script replaces the dashboard rather
    # than leaving near-duplicates side by side.
    assert model["uid"] == "lesysbot-node"
    ids = [p["id"] for p in model["panels"]]
    assert len(ids) == len(set(ids))
    for panel in model["panels"]:
        assert panel["gridPos"]["x"] + panel["gridPos"]["w"] <= 24
        assert panel["gridPos"]["w"] > 0


def test_cli_rejects_capabilities_the_host_cannot_have(gen):
    """A typo in the start script must fail loudly, not drop a dashboard row."""
    with pytest.raises(SystemExit):
        gen.main(["--host", "linux", "--have", "definitely_not_a_capability"])


# ----------------------------------------------------------- portable dashboard
def test_portable_dashboard_asks_for_every_sensor_family(gen):
    """Un-probed, it cannot know which chips exist, so it must query them all —
    an absent one simply renders empty."""
    exprs = _exprs(gen.build_node())
    assert "node_memory_SwapTotal_bytes" in exprs
    assert CPU_CHIPS_MARKER in exprs
    assert "nvme|drivetemp" in exprs


def test_bundled_json_matches_the_generator(gen, tmp_path):
    """The committed JSON is generated output — regenerate rather than hand-edit."""
    out = SCRIPT.resolve().parent.parent / "grafana" / "dashboards"
    name = "system-overview.json"
    assert json.loads((out / name).read_text()) == gen.build_node(), (
        f"{name} is stale — re-run: python3 dashboard/scripts/gen-dashboards.py"
    )
