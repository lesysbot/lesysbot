"""Tests for the capability detection in dashboard/scripts/install-macos.sh.

The counterpart to `test_start_detect.py`, and it exists because of a bug that
one caught and this didn't: `start.sh` and `install-macos.sh` both ask
`gen-dashboards.py` for a dashboard cut, the generator's CLI changed from
`--macos/--intel/--nvidia` to `--host/--have`, and only `start.sh` was migrated.
The installer swallowed the generator's stderr, so argparse's exit-2 was
invisible and every Mac silently fell back to the *portable* dashboard — the one
carrying Linux hwmon rows that a Mac can never fill, which is exactly the symptom
the per-host cut was built to eliminate.

`install-macos.sh` returns early when sourced rather than executed (before its
Darwin and Homebrew preflight), so these drive `dashboard_caps` directly. That is
what lets them run on Linux CI, where the whole script could otherwise never be
exercised at all.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "dashboard" / "scripts" / "install-macos.sh"
GEN = SCRIPT.parent / "gen-dashboards.py"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _caps(arm64: bool = True, nvidia: bool = False) -> str:
    """Source the script and run its cap builder with the two host facts forced.

    Architecture and nvidia-smi are the only inputs, and both come from the
    machine — so they're overridden after sourcing, the same shape as
    test_start_detect.py overriding `is_virtual` / `command -v`.
    """
    script = f"""
      set -euo pipefail
      source {SCRIPT}
      MAC_ARCH={'arm64' if arm64 else 'x86_64'}
      has_nvidia() {{ return {0 if nvidia else 1}; }}
      printf 'CAPS=%s\\n' "$(dashboard_caps)"
    """
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    for line in out.stdout.splitlines():
        if line.startswith("CAPS="):
            return line[len("CAPS="):]
    raise AssertionError(f"no CAPS line in output: {out.stdout!r}")


def test_apple_silicon_without_nvidia_claims_nothing():
    """The overwhelmingly common Mac: no capability flags at all, which must be
    an empty --have rather than a missing one."""
    assert _caps(arm64=True, nvidia=False) == ""


def test_intel_is_claimed_only_on_intel():
    """node_exporter's thermal collector is Intel-only; claiming it on an M-series
    Mac provisions throttling panels that report nothing."""
    assert _caps(arm64=False, nvidia=False) == "intel"
    assert "intel" not in _caps(arm64=True, nvidia=False)


def test_nvidia_tracks_the_driver_not_the_hardware():
    """nvidia_gpu_exporter shells out to nvidia-smi, so no driver means nothing
    can be scraped — the same rule start.sh follows."""
    assert _caps(arm64=True, nvidia=True) == "nvidia"
    assert _caps(arm64=False, nvidia=True) == "intel,nvidia"


@pytest.mark.parametrize("arm64,nvidia", [(True, False), (True, True), (False, False), (False, True)])
def test_detected_capabilities_are_accepted_by_the_generator(tmp_path, arm64, nvidia):
    """The regression guard: every cap string this script can emit must be one
    the generator accepts. This is the test whose absence let the installer keep
    calling a CLI that had been removed."""
    out = tmp_path / "dash.json"
    subprocess.run(["python3", str(GEN), "--host", "macos",
                    "--have", _caps(arm64=arm64, nvidia=nvidia), "--out", str(out)],
                   check=True, capture_output=True)
    assert out.exists()


def test_generator_stderr_is_not_swallowed():
    """The failure was invisible because the call redirected stderr to /dev/null.
    Keeping the diagnostic is the difference between a warning that names the
    problem and a Mac that quietly runs the wrong dashboard for months."""
    text = SCRIPT.read_text()
    assert "--host macos --have" in text, "installer must use the current generator CLI"
    assert "--macos" not in text, "stale generator flags are back"
    # The one invocation captures stderr for the warning instead of discarding it.
    assert '2>&1 >/dev/null' in text
