"""GPU detection, keyed on the *tool* rather than the card.

This is the case the whole prerequisite layer exists for. A machine with an
RTX 3080 and no driver is not "a machine without a GPU" — it is a machine one
download away from working, and saying "unavailable" to it is the difference
between a product that helps and one that shrugs.

The rule the stack's start scripts already follow, generalized: **key on whether
the reading tool exists**, because `nvidia_gpu_exporter` and `nvidia-smi` are how
anything actually gets a number. Hardware probes (`lspci`, `system_profiler`,
`Win32_VideoController`) are consulted *only to explain* an omission and to name
the driver worth installing — never to decide that a GPU is usable.
"""

from __future__ import annotations

import platform
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


def _current_os() -> str:
    from lesysbot.mcp.platform import current_os

    return current_os()


def _nvidia_hardware() -> str:
    """A model name when an NVIDIA card is visibly present, else ""."""
    system = _current_os()
    if system == "linux":
        for line in _run(["lspci"]).splitlines():
            if "nvidia" in line.lower() and any(
                k in line.lower() for k in ("vga", "3d controller", "display")
            ):
                return line.split(":")[-1].strip()
    elif system == "windows":
        out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_VideoController).Name"])
        for line in out.splitlines():
            if "nvidia" in line.lower():
                return line.strip()
    elif system == "macos":
        # Apple dropped NVIDIA support entirely; a card here is an old eGPU.
        out = _run(["system_profiler", "SPDisplaysDataType"])
        for line in out.splitlines():
            if "nvidia" in line.lower():
                return line.strip().rstrip(":")
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
            fix=_LINUX_NVIDIA_FIX if _current_os() == "linux"
                else f"install the NVIDIA driver — {NVIDIA_DRIVERS}",
        )
    return GPUInfo("nvidia", detail="no NVIDIA GPU found")


def detect_amd() -> GPUInfo:
    """AMD. On Linux, temperatures come from hwmon and need no exporter at all."""
    if shutil.which("rocm-smi"):
        return GPUInfo("amd", usable=True, hardware_present=True, detail="rocm-smi present")
    if _current_os() == "linux":
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


def detect_apple() -> GPUInfo:
    """Apple silicon's integrated GPU, readable through ioreg without sudo."""
    if _current_os() != "macos":
        return GPUInfo("apple", detail="not a Mac")
    if platform.machine() == "arm64":
        return GPUInfo("apple", usable=True, hardware_present=True,
                       detail="Apple silicon GPU (ioreg)")
    return GPUInfo("apple", detail="Intel Mac — no Apple GPU")


_DETECTORS = {"nvidia": detect_nvidia, "amd": detect_amd, "apple": detect_apple}


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
