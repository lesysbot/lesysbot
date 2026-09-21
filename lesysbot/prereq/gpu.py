"""GPU detection, keyed on the *tool* rather than the card.

This is the case the whole prerequisite layer exists for. A machine with an
RTX 3080 and no driver is not "a machine without a GPU" — it is a machine one
download away from working, and saying "unavailable" to it is the difference
between a product that helps and one that shrugs.

The rule the stack's start script already follows, generalized: **key on whether
the reading tool exists**, because `nvidia_gpu_exporter` and `nvidia-smi` are how
anything actually gets a number. The hardware probe (`lspci`) is consulted *only
to explain* an omission and to name the driver worth installing — never to decide
that a GPU is usable.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

NVIDIA_DRIVERS = "https://www.nvidia.com/download/index.aspx"

# Distro-appropriate, unprivileged-where-possible driver hints. `sudo` appears
# in the *text* for the cases where no unprivileged route exists — telling
# someone the truth is not the same as running it for them.
_LINUX_NVIDIA_FIX = (
    "install the NVIDIA driver (Ubuntu: `sudo ubuntu-drivers install`, "
    f"Fedora: RPM Fusion `akmod-nvidia`, or {NVIDIA_DRIVERS})"
)


@dataclass
class GPUInfo:
    """What we could learn about one GPU vendor on this machine."""

    vendor: str
    #: A reading tool is on PATH, so metrics can actually be collected.
    usable: bool = False
    #: Hardware appears present even though nothing can read it.
    hardware_present: bool = False
    detail: str = ""
    fix: str = ""


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    """Best-effort command output; "" when it fails, is missing, or hangs."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _nvidia_hardware() -> str:
    """A model name when an NVIDIA card is visibly present, else ""."""
    for line in _run(["lspci"]).splitlines():
        if "nvidia" in line.lower() and any(
            k in line.lower() for k in ("vga", "3d controller", "display")
        ):
            return line.split(":")[-1].strip()
    return ""


def detect_nvidia() -> GPUInfo:
    """NVIDIA, split into 'usable', 'driver missing', and 'no card'."""
    if shutil.which("nvidia-smi"):
        name = _run(["nvidia-smi", "--query-gpu=name",
                     "--format=csv,noheader"]).strip().splitlines()
        detail = name[0].strip() if name else "nvidia-smi present"
        return GPUInfo("nvidia", usable=True, hardware_present=True, detail=detail)

    hardware = _nvidia_hardware()
    if hardware:
        return GPUInfo(
            "nvidia",
            hardware_present=True,
            detail=f"{hardware} present, but no driver is installed",
            fix=_LINUX_NVIDIA_FIX,
        )
    return GPUInfo("nvidia", detail="no NVIDIA GPU found")


def detect_amd() -> GPUInfo:
    """AMD. On Linux, temperatures come from hwmon and need no exporter at all."""
    if shutil.which("rocm-smi"):
        return GPUInfo("amd", usable=True, hardware_present=True, detail="rocm-smi present")
    for line in _run(["lspci"]).splitlines():
        low = line.lower()
        if ("amd" in low or "radeon" in low) and any(
            k in low for k in ("vga", "3d controller", "display")
        ):
            # amdgpu exposes temperature through hwmon, which node_exporter
            # already scrapes — so this is usable without any extra tool.
            return GPUInfo("amd", usable=True, hardware_present=True,
                           detail="amdgpu via hwmon (no exporter needed)")
    return GPUInfo("amd", detail="no AMD GPU found")


_DETECTORS = {"nvidia": detect_nvidia, "amd": detect_amd}


def detect(vendor: str) -> GPUInfo:
    """Detect one vendor by name; unknown vendors report as not found."""
    key = (vendor or "").strip().lower()
    detector = _DETECTORS.get(key)
    if detector is None:
        return GPUInfo(key or "gpu", detail=f"unknown GPU vendor {vendor!r}")
    return detector()


def detect_all() -> list[GPUInfo]:
    """Every vendor, for `lesysbot doctor`."""
    return [detector() for detector in _DETECTORS.values()]
