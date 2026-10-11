#!/usr/bin/env bash
# One command to bring up the whole system-overview stack.
#
#   ./scripts/start.sh                      # start everything, detecting what this host has
#   ./scripts/start.sh up --grafana-port N  # ...with Grafana on port N (saved in .env)
#   ./scripts/start.sh down                 # stop and remove the stack
#
# Prometheus + Grafana + node-exporter run on the host network. NVIDIA GPU
# metrics run as a container when the nvidia-container-toolkit is present,
# otherwise as a native exporter — both automatic.
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

# Fill grafana/dashboards/generated/ — the directory the compose mounts — with
# the one dashboard, best source first:
#
#   1. dashboard.json next to this stack, when the user has their own copy
#      (`lesysbot dashboard customize` makes one). Used as-is, never touched.
#   2. gen-dashboards.py for this host, with the sensors probed above.
#   3. The committed portable JSON, when there is no python3 at all.
#
# Anything else in the directory is removed first: Grafana provisions every
# JSON it finds there, so a file left by an older release (when dashboards were
# separate packages) would keep showing up as a second dashboard.
#
# The directory is created either way: Docker creates a missing bind-mount
# source as a root-owned directory, which then can't be written without sudo.
DASH_DEFAULT=system-overview.json
GENERATED="$ROOT/grafana/dashboards/generated"
CUSTOM="$ROOT/dashboard.json"

select_dashboard() {
  local gen="$HERE/gen-dashboards.py" out="$GENERATED/$DASH_DEFAULT"
  mkdir -p "$GENERATED"
  rm -f "$GENERATED"/*.json

  if [ -f "$CUSTOM" ]; then
    cp "$CUSTOM" "$out"
    echo "==> using your dashboard ($CUSTOM)"
    echo "    Back to the automatic one:  lesysbot dashboard reset"
    return
  fi
  if ! command -v python3 >/dev/null 2>&1 || [ ! -f "$gen" ]; then
    cp "$ROOT/grafana/dashboards/$DASH_DEFAULT" "$out" 2>/dev/null || true
    echo "==> using the portable dashboard (no python3 to generate one)"
    return
  fi
  if python3 "$gen" --host linux --have "$CAPS" --out "$out" >/dev/null 2>&1; then
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

# --- Grafana's port -----------------------------------------------------------
# Grafana binds 127.0.0.1:$GRAFANA_PORT on the host network. If anything else
# already listens there it crash-loops on "address already in use" and the
# dashboard just never appears — and 3000 is every web dev server's default. So
# a taken port is detected here and Grafana moves to the next free one, saved
# in .env so the move sticks and LeSysBot (which reads .env) finds it there.
# An explicit --grafana-port is a choice, not a hint: it is used or refused,
# never silently swapped for another.
PORT_SEARCH_SPAN=100

env_get() { grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- || true; }
env_set() {
  if grep -qE "^$1=" .env 2>/dev/null; then
    sed -i "s/^$1=.*/$1=$2/" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}

# Is something listening on 127.0.0.1:PORT? (bash's /dev/tcp — no extra tools)
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# The port our own Grafana container is healthily serving, or nothing. A
# restarting container is crash-looping (usually on exactly this conflict), so
# it holds no port.
our_grafana_port() {
  docker inspect -f '{{.State.Running}} {{.State.Restarting}}{{range .Config.Env}} {{.}}{{end}}' \
    lesysbot-grafana 2>/dev/null |
    awk '$1 == "true" && $2 == "false" {
      for (i = 3; i <= NF; i++) if ($i ~ /^GF_SERVER_HTTP_PORT=/) { sub(/^[^=]*=/, "", $i); print $i }
    }' || true
}

valid_port() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }

# Settle GRAFANA_PORT before `compose up`. $1 is an explicit choice, or empty.
choose_grafana_port() {
  local want="${1:-}" prom next p
  if [ -n "$want" ]; then
    if ! valid_port "$want"; then
      echo "✗ --grafana-port needs a port number (1-65535), got '$want'." >&2
      return 1
    fi
    if port_busy "$want" && [ "$(our_grafana_port)" != "$want" ]; then
      echo "✗ Port $want is already used by another program. Pick a free one." >&2
      return 1
    fi
    [ "$want" = "$PORT" ] || echo "==> Grafana port set to $want (saved in .env)"
    env_set GRAFANA_PORT "$want"
    PORT="$want"
    return 0
  fi

  port_busy "$PORT" || return 0
  [ "$(our_grafana_port)" = "$PORT" ] && return 0

  prom="$(env_get PROM_PORT)"; prom="${prom:-9090}"
  next=""
  p=$((PORT + 1))
  while [ "$p" -le $((PORT + PORT_SEARCH_SPAN)) ]; do
    if [ "$p" != "$prom" ] && ! port_busy "$p"; then next="$p"; break; fi
    p=$((p + 1))
  done
  if [ -z "$next" ]; then
    echo "✗ Port $PORT is used by another program and no free port was found after it." >&2
    echo "  Choose one:  $0 up --grafana-port <port>" >&2
    return 1
  fi
  echo "==> Port $PORT is used by another program; Grafana moves to $next (saved in .env)."
  echo "    Prefer a different one?  $0 up --grafana-port <port>"
  env_set GRAFANA_PORT "$next"
  PORT="$next"
}

down() {
  dc --profile gpu down
  "$HERE/run-exporters.sh" stop 2>/dev/null || true
}

# Fill the dashboard, then start the containers. A function, above the
# sourcing guard, so tests/test_start_detect.py can drive it with docker stubbed.
start_stack() {
  select_dashboard
  if command -v nvidia-smi >/dev/null 2>&1; then
    if has_nvidia_runtime; then
      echo "==> NVIDIA (container runtime): full stack on the host network"
      dc --profile gpu up -d
    else
      echo "==> NVIDIA (no container toolkit): stack + native GPU exporter"
      dc up -d
      "$HERE/run-exporters.sh" nvidia     # port 9100 is taken by the container
    fi
  else
    echo "==> No NVIDIA GPU detected: starting stack without GPU"
    dc up -d
  fi
}

# Sourcing this file defines the functions above and stops there, so the
# detection can be driven against a fixture tree (see tests/test_start_detect.py)
# without Docker, without root and without starting anything.
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
  return 0
fi

usage() {
  echo "usage: $0 [up [--grafana-port N] | down]" >&2
  exit 2
}

main() {
local action=up want_port=""
while [ $# -gt 0 ]; do
  case "$1" in
    up|down) action="$1" ;;
    --grafana-port) [ $# -ge 2 ] || usage; want_port="$2"; shift ;;
    --grafana-port=*) want_port="${1#*=}" ;;
    *) usage ;;
  esac
  shift
done

preflight
if [ "$action" = "down" ]; then down; echo "stack stopped."; exit 0; fi

choose_grafana_port "$want_port" || exit 1
detect_capabilities_linux
start_stack

cat <<EOF

  Grafana:    http://localhost:${PORT}      (admin / admin — change it)
  Prometheus: http://localhost:9090/targets (your exporters should be 'up')

  Dashboard is under the "LeSysBot" folder in Grafana.
  Change it:  lesysbot dashboard customize
  Stop with:  ./scripts/start.sh down
EOF

report_missing
}

main "$@"
