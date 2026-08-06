#!/usr/bin/env bash
# One command to bring up the whole system-overview stack on Linux or macOS.
#
#   ./scripts/start.sh          # start everything the right way for this OS
#   ./scripts/start.sh down     # stop and remove the stack
#
# Linux  : Prometheus + Grafana + node-exporter on the host network. NVIDIA GPU
#          metrics run as a container when the nvidia-container-toolkit is
#          present, otherwise as a native exporter — both automatic.
# macOS  : native host exporters, then Prometheus + Grafana in Docker Desktop.
# Windows: use scripts\start.ps1 instead.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$ROOT"

# Grafana host port, for the closing message (compose reads .env itself).
PORT="$(grep -E '^GRAFANA_PORT=' .env 2>/dev/null | cut -d= -f2 || true)"
PORT="${PORT:-3000}"

dc() { docker compose "$@"; }   # docker compose v2

# --- preflight: fail early with a helpful message, not a stack trace ----------
preflight() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "✗ Docker is not installed. Install it first — see dashboard/README.md → Prerequisites." >&2
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "✗ Docker Compose v2 is missing ('docker compose'). Update Docker / Docker Desktop." >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "✗ Can't talk to the Docker daemon. Either it isn't running or you lack permission:" >&2
    echo "    • Start it:   Docker Desktop, or  sudo systemctl start docker" >&2
    echo "    • Linux perms: sudo usermod -aG docker \$USER   (then log out and back in)" >&2
    exit 1
  fi
}

# Does Docker expose the NVIDIA container runtime? (nvidia-container-toolkit)
has_nvidia_runtime() { docker info 2>/dev/null | grep -qiE 'runtimes:.*nvidia'; }

# --- what sensors does this host actually have? ------------------------------
# node_exporter's hwmon collector can only report chips the kernel has bound a
# driver to, so the presence of a chip name under /sys is exactly the question
# "can this panel ever have data?". Reading /sys directly (rather than probing
# the exporter) works before anything is started, and needs no root.
#
# CAPS becomes the --have list for gen-dashboards.py; MISSING collects the
# add-ons worth telling the user about. Both stay empty on a machine with no
# sensors at all (a VM, a container host), which is itself worth saying.
CAPS=""
MISSING=""
add_cap()     { CAPS="${CAPS:+$CAPS,}$1"; }
add_missing() { MISSING="${MISSING}
  • $1"; }

# SYSFS_ROOT exists so tests can point the probe at a fixture tree; nothing else
# sets it. It's the real glob either way — the thing worth testing is which chip
# names map to which capability, not the reading itself.
SYSFS_ROOT="${SYSFS_ROOT:-/sys}"
hwmon_names() { cat "$SYSFS_ROOT"/class/hwmon/*/name 2>/dev/null || true; }

is_virtual() {
  if command -v systemd-detect-virt >/dev/null 2>&1; then
    systemd-detect-virt --quiet 2>/dev/null && return 0
  fi
  return 1
}

detect_capabilities_linux() {
  local names; names="$(hwmon_names)"

  if printf '%s' "$names" | grep -qE '^(coretemp|k10temp|zenpower|cpu_thermal)$'; then
    add_cap cpu_temp
  else
    # No CPU chip is normal in a VM and fixable on bare metal, so distinguish.
    if ! is_virtual; then
      add_missing "No CPU temperature sensor. On Intel/AMD desktops the driver is
    usually just not loaded — try:  sudo modprobe coretemp   (Intel)
                                    sudo modprobe k10temp    (AMD)
    and add the name to /etc/modules-load.d/ to make it stick."
    fi
  fi

  if printf '%s' "$names" | grep -qE '^(nvme|drivetemp)$'; then
    add_cap disk_temp
  elif ! is_virtual; then
    add_missing "No disk temperature sensor. NVMe drives report it with no setup;
    SATA drives need the drivetemp module:  sudo modprobe drivetemp
    (echo drivetemp | sudo tee /etc/modules-load.d/drivetemp.conf  to persist)."
  fi

  printf '%s' "$names" | grep -qE '^amdgpu$' && add_cap amd_gpu
  [ -e "$SYSFS_ROOT/class/thermal/thermal_zone0" ] && add_cap thermal_zone
  command -v nvidia-smi >/dev/null 2>&1 && add_cap nvidia

  # An NVIDIA card with no driver can't be scraped by anything, so it's an
  # add-on to recommend rather than a capability to claim.
  if ! command -v nvidia-smi >/dev/null 2>&1 &&
     command -v lspci >/dev/null 2>&1 && lspci 2>/dev/null | grep -qi 'nvidia'; then
    add_missing "An NVIDIA GPU is present but nvidia-smi isn't installed, so its
    metrics can't be read. Install your distro's NVIDIA driver package
    (which ships nvidia-smi), then re-run this script."
  fi
}

# macOS through Docker Desktop. The native path (install-macos.sh) does its own,
# richer detection; this only has to get the Docker stack's dashboard right.
detect_capabilities_macos() {
  [ "$(uname -m)" = "arm64" ] || add_cap intel
  command -v nvidia-smi >/dev/null 2>&1 && add_cap nvidia
  add_missing "CPU/GPU die temperature needs a helper on macOS:
    brew install vladkens/tap/macmon   (Apple Silicon)
    brew install narugit/tap/smctemp   (Intel or Apple Silicon)
    Or use ./scripts/install-macos.sh, which offers to install one for you."
}

# Fill grafana/dashboards/generated/ — the directory the compose mounts. Three
# routes, best first:
#
#   1. `lesysbot dashboard render` renders every *installed* dashboard package,
#      so a user's own dashboards come up alongside System Overview.
#   2. gen-dashboards.py for this host, when LeSysBot isn't on PATH (running the
#      stack straight from a checkout).
#   3. The committed portable JSON, when there is no python3 at all.
#
# The directory is created either way: Docker creates a missing bind-mount
# source as a root-owned directory, which then can't be written without sudo.
DASH_DEFAULT=system-overview-linux-macos.json
GENERATED="$ROOT/grafana/dashboards/generated"

select_dashboard() { # $1 = linux|macos
  local gen="$HERE/gen-dashboards.py" out="$GENERATED/system-overview.json"
  mkdir -p "$GENERATED"

  if command -v lesysbot >/dev/null 2>&1 && lesysbot dashboard render >/dev/null 2>&1; then
    echo "==> dashboards rendered by lesysbot"
    return
  fi
  if ! command -v python3 >/dev/null 2>&1 || [ ! -f "$gen" ]; then
    cp "$ROOT/grafana/dashboards/$DASH_DEFAULT" "$out" 2>/dev/null || true
    echo "==> using the portable dashboard (no python3 to generate one)"
    return
  fi
  if python3 "$gen" --host "$1" --have "$CAPS" --out "$out" >/dev/null 2>&1; then
    echo "==> dashboard generated for this host [${CAPS:-no optional sensors detected}]"
  else
    cp "$ROOT/grafana/dashboards/$DASH_DEFAULT" "$out" 2>/dev/null || true
    echo "==> using the portable dashboard (couldn't generate one)" >&2
  fi
}

report_missing() {
  [ -n "$MISSING" ] || return 0
  cat >&2 <<EOF

  Optional add-ons that would fill in more panels:$MISSING

  Everything else is already being recorded — these are additions, not errors.
EOF
}

down() {
  case "$(uname -s)" in
    Linux)  dc -f docker-compose.linux.yml --profile gpu down; "$HERE/run-exporters.sh" stop 2>/dev/null || true ;;
    Darwin) dc down; "$HERE/run-exporters.sh" stop ;;
  esac
}

# Sourcing this file defines the functions above and stops there, so the
# detection can be driven against a fixture tree (see tests/test_start_detect.py)
# without Docker, without root and without starting anything.
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
  return 0
fi

main() {
preflight
if [ "${1:-up}" = "down" ]; then down; echo "stack stopped."; exit 0; fi

case "$(uname -s)" in
  Linux)
    detect_capabilities_linux
    select_dashboard linux
    if command -v nvidia-smi >/dev/null 2>&1; then
      if has_nvidia_runtime; then
        echo "==> Linux + NVIDIA (container runtime): full stack on the host network"
        dc -f docker-compose.linux.yml --profile gpu up -d
      else
        echo "==> Linux + NVIDIA (no container toolkit): stack + native GPU exporter"
        dc -f docker-compose.linux.yml up -d
        "$HERE/run-exporters.sh" nvidia     # port 9100 is taken by the container
      fi
    else
      echo "==> Linux (no NVIDIA GPU detected): starting stack without GPU"
      dc -f docker-compose.linux.yml up -d
    fi
    ;;
  Darwin)
    detect_capabilities_macos
    select_dashboard macos
    echo "==> macOS: starting native host exporters"
    "$HERE/run-exporters.sh" start
    echo "==> starting Prometheus + Grafana (Docker Desktop)"
    dc up -d
    ;;
  *)
    echo "Unsupported OS $(uname -s). On Windows run: .\\scripts\\start.ps1" >&2
    exit 1
    ;;
esac

cat <<EOF

  Grafana:    http://localhost:${PORT}      (admin / admin — change it)
  Prometheus: http://localhost:9090/targets (your exporters should be 'up')

  Dashboard is under the "LeSysBot" folder in Grafana.
  Stop with:  ./scripts/start.sh down
EOF

report_missing
}

main "$@"
