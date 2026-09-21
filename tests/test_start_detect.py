"""Tests for the Linux sensor detection in dashboard/scripts/start.sh.

`start.sh` returns early when sourced rather than executed, so these drive its
detection functions directly against a fixture `/sys` tree (`SYSFS_ROOT`) — no
Docker, no root, nothing started. That also means they run on macOS and on Linux
CI alike, which matters: the logic being tested is *Linux* behaviour that a Mac
developer would otherwise never exercise.

What's worth pinning is the mapping from hwmon chip name to dashboard
capability. Get it wrong in the permissive direction and a panel is provisioned
that can never fill (the bug this whole mechanism exists to prevent); get it
wrong the other way and a working sensor silently goes unrecorded.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "dashboard" / "scripts" / "start.sh"

# Windows is excluded deliberately, not because the harness is awkward there.
# `start.sh` brings up the *Linux* Docker stack; Windows runs `start.ps1`
# instead, so sourcing this under Git Bash would exercise a path that never runs
# on a Windows machine. It would also fail on the paths alone: `bash` is on PATH
# on the runners, so the which() guard below does not fire, and a Windows path
# interpolated into a bash string has its separators eaten as escapes
# (`D:\a\lesysbot\…` sources as `D:alesysbot…`).
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="drives a Linux-only shell script; needs a POSIX bash",
)


_counter = iter(range(10_000))


def _sysfs(tmp_path: Path, chips: list[str], thermal_zone: bool = True) -> Path:
    # A fresh root per call, so one test can build several trees.
    root = tmp_path / f"sys{next(_counter)}"
    (root / "class" / "hwmon").mkdir(parents=True)
    for i, chip in enumerate(chips):
        d = root / "class" / "hwmon" / f"hwmon{i}"
        d.mkdir()
        (d / "name").write_text(chip + "\n")
    if thermal_zone:
        (root / "class" / "thermal" / "thermal_zone0").mkdir(parents=True)
    return root


def _detect(sysfs: Path, virtual: bool = False, nvidia: bool = False) -> tuple[str, str]:
    """Source start.sh, run the Linux probe, return (caps, missing).

    `is_virtual` and the nvidia-smi lookup are the two things that depend on the
    machine rather than on /sys, so they're overridden after sourcing — the same
    shape as test_macos_metrics.py stubbing `_run`.
    """
    script = f"""
      set -euo pipefail
      export SYSFS_ROOT={sysfs}
      source {SCRIPT}
      is_virtual() {{ return {0 if virtual else 1}; }}
      command() {{
        if [ "$2" = nvidia-smi ]; then return {0 if nvidia else 1}; fi
        builtin command "$@"
      }}
      detect_capabilities_linux
      printf 'CAPS=%s\\n' "$CAPS"
      printf 'MISSING=%s\\n' "$MISSING"
    """
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    caps = missing = ""
    for line in out.stdout.splitlines():
        if line.startswith("CAPS="):
            caps = line[len("CAPS="):]
        elif line.startswith("MISSING="):
            missing = line[len("MISSING="):]
    return caps, out.stdout[out.stdout.index("MISSING="):] if "MISSING=" in out.stdout else missing


@pytest.mark.parametrize("chip", ["coretemp", "k10temp", "zenpower", "cpu_thermal"])
def test_cpu_chips_are_recognised(tmp_path, chip):
    """Intel, AMD (two drivers) and ARM all report CPU temperature under
    different chip names; missing one silently drops the CPU panel."""
    caps, _ = _detect(_sysfs(tmp_path, [chip]))
    assert "cpu_temp" in caps.split(",")


@pytest.mark.parametrize("chip", ["nvme", "drivetemp"])
def test_disk_chips_are_recognised(tmp_path, chip):
    caps, _ = _detect(_sysfs(tmp_path, [chip]))
    assert "disk_temp" in caps.split(",")


def test_amd_gpu_is_its_own_capability(tmp_path):
    """amdgpu is an hwmon chip, not an exporter — it must not be mistaken for
    the NVIDIA row, which needs nvidia-smi."""
    caps, _ = _detect(_sysfs(tmp_path, ["amdgpu"]))
    assert "amd_gpu" in caps.split(",")
    assert "nvidia" not in caps.split(",")


def test_unrelated_chips_claim_nothing(tmp_path):
    """A laptop full of battery/charger/wifi hwmon entries must not be read as
    a CPU or disk sensor — that provisions panels that can never fill."""
    caps, _ = _detect(_sysfs(tmp_path, ["BAT0", "acpitz", "iwlwifi_1"], thermal_zone=False))
    assert caps == ""


def test_thermal_zone_detected_independently(tmp_path):
    caps, _ = _detect(_sysfs(tmp_path, [], thermal_zone=True))
    assert caps.split(",") == ["thermal_zone"]


def test_bare_metal_without_sensors_gets_advice(tmp_path):
    """The modprobe hints are the actionable half — a bare-metal box with no
    coretemp almost always just needs the module loaded."""
    _, missing = _detect(_sysfs(tmp_path, [], thermal_zone=False), virtual=False)
    assert "modprobe coretemp" in missing
    assert "modprobe drivetemp" in missing


def test_virtual_machines_are_not_told_to_modprobe(tmp_path):
    """A VM has no sensors to expose, so the advice would be a dead end."""
    _, missing = _detect(_sysfs(tmp_path, [], thermal_zone=False), virtual=True)
    assert "modprobe" not in missing


def test_nvidia_comes_from_the_driver_not_from_sysfs(tmp_path):
    """nvidia_gpu_exporter shells out to nvidia-smi, so a card without a driver
    cannot be scraped — the capability has to track the tool, not the hardware."""
    caps, _ = _detect(_sysfs(tmp_path, ["coretemp"]), nvidia=True)
    assert "nvidia" in caps.split(",")
    caps, _ = _detect(_sysfs(tmp_path, ["coretemp"]), nvidia=False)
    assert "nvidia" not in caps.split(",")


def test_detected_capabilities_are_accepted_by_the_generator(tmp_path):
    """The two scripts have to agree on the capability vocabulary; a typo in
    either is a usage error rather than a quietly missing dashboard row."""
    gen = SCRIPT.parent / "gen-dashboards.py"
    caps, _ = _detect(_sysfs(tmp_path, ["coretemp", "nvme", "amdgpu"]), nvidia=True)
    out = tmp_path / "dash.json"
    subprocess.run(["python3", str(gen), "--host", "linux", "--have", caps,
                    "--out", str(out)], check=True, capture_output=True)
    assert out.exists()
