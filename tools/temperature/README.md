---
name: temperature
description: CPU and GPU temperature readings (hwmon + nvidia-smi)
version: 1.0.0
requires: []
---
# temperature

Reports current **CPU and GPU temperatures** in one call. CPU (and
AMD/Intel/nouveau GPU) readings come from the kernel's hwmon interface
(`/sys/class/hwmon`) — no external binary or pip dependency. NVIDIA GPUs are
read via `nvidia-smi` when it's on PATH (the proprietary driver doesn't expose
temperatures through hwmon).

**Needs:** nothing (`nvidia-smi` used if present)

This replaces the separate `cpu-temp` and `gpu-temp` packages — one call now
answers "how hot is it?" for both.

## Tools
- `/temperature` — grouped CPU/GPU readings, e.g.:

  ```
  CPU:
    coretemp Package id 0: 47°C
    coretemp 24 cores: 35–47°C
  GPU:
    GPU0 NVIDIA GeForce RTX 3080: 51°C
  ```

  Per-core temperatures are compacted into one `min–max` range line; chip-level
  readings (`Package id 0`, `Tctl`, `edge`, …) are listed individually.

Recognized CPU sensors: `coretemp` (Intel), `k10temp`/`zenpower` (AMD),
`cpu_thermal` (ARM SoCs, e.g. Raspberry Pi). GPU sensors: `amdgpu`, `radeon`,
`nouveau`, `i915`, `xe`, plus `nvidia-smi`. A board that publishes its CPU only
as a **thermal zone** (`/sys/class/thermal`) is covered by a fallback, used
only when hwmon found no CPU reading — otherwise the same sensor would appear
twice. If nothing is found the tool says so instead of failing; running
lm-sensors' `sensors-detect` can load missing kernel modules.

## Copy-paste
Drop this `temperature/` folder into your `~/.lesysbot/tools/` and restart LeSysBot.
