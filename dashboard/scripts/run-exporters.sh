#!/usr/bin/env bash
# Run the host metric exporters natively, outside Docker.
#
#   ./run-exporters.sh [start|nvidia|stop|status|restart]   (default: start)
#
# Starts, in the background:
#   * node_exporter        :9100  — CPU, memory, disk, filesystem, Ethernet, Wifi
#   * nvidia_gpu_exporter  :9835  — GPU (only if `nvidia-smi` is on PATH)
#
# Binaries are downloaded once into dashboard/bin/. PIDs and logs live in
# dashboard/run/. Prometheus (in Docker) scrapes these via host.docker.internal.
#
# The bundled stack already runs node-exporter in a container, so port 9100 is
# normally taken — this script detects that and starts only the GPU exporter.
# That is exactly the case `start.sh` uses it for: an NVIDIA box without the
# nvidia-container-toolkit.
set -euo pipefail

NODE_VERSION="1.8.2"
NVIDIA_VERSION="1.3.2"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
BIN="$ROOT/bin"
RUN="$ROOT/run"
mkdir -p "$BIN" "$RUN"

# EXPORTER_BIND overrides the address the exporters listen on. The native macOS
# stack (scripts/install-macos.sh) sets it to 127.0.0.1, because there Prometheus
# runs on the host too and nothing in that stack should be reachable off-box.
case "$(uname -s)" in
  # macOS runs Prometheus in the Docker Desktop VM, which reaches the host via
  # host.docker.internal — the exporter must listen on all interfaces (0.0.0.0).
  # Linux runs Prometheus on the host network, so localhost is enough and keeps
  # the exporter off the LAN.
  Linux)  OS=linux;  NODE_OS=linux;  NV_OS=linux;  BIND="${EXPORTER_BIND:-127.0.0.1}" ;;
  Darwin) OS=darwin; NODE_OS=darwin; NV_OS=darwin; BIND="${EXPORTER_BIND:-0.0.0.0}" ;;
  *) echo "Unsupported OS $(uname -s). On Windows use run-exporters.ps1." >&2; exit 1 ;;
esac
NODE_ADDR="$BIND:9100"
NVIDIA_ADDR="$BIND:9835"
case "$(uname -m)" in
  x86_64|amd64)  NODE_ARCH=amd64; NV_ARCH=x86_64 ;;
  arm64|aarch64) NODE_ARCH=arm64; NV_ARCH=arm64 ;;
  *) echo "Unsupported CPU arch $(uname -m)." >&2; exit 1 ;;
esac

# Log to stderr: these functions are also called inside $(...) command
# substitution (ensure_node/ensure_nvidia return a path on stdout), so anything
# on stdout would be captured as part of that path.
log()  { printf '\033[1;34m[exporters]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m[exporters]\033[0m %s\n' "$*" >&2; }

port_busy() { # $1 = port
  if command -v nc >/dev/null 2>&1; then nc -z 127.0.0.1 "$1" >/dev/null 2>&1
  else curl -fsS --max-time 1 "http://127.0.0.1:$1" >/dev/null 2>&1; fi
}

download() { # $1 url  $2 dest
  log "downloading $(basename "$1")"
  curl -fL --retry 3 -o "$2" "$1"
}

# Download + extract into a private temp dir, then move the one binary out. Keeps
# the archive layout (bare binary vs. versioned subdir) from mattering and avoids
# any chance of `cp` seeing identical source/destination paths.
fetch_binary() { # $1 url  $2 binary-name -> prints final path on stdout
  local url="$1" name="$2" bin="$BIN/$2"
  [ -x "$bin" ] && { echo "$bin"; return; }
  local tmp; tmp="$(mktemp -d "$BIN/.dl.XXXXXX")"
  download "$url" "$tmp/archive"
  tar -xzf "$tmp/archive" -C "$tmp"
  local found; found="$(find "$tmp" -name "$name" -type f | head -1)"
  [ -n "$found" ] || { warn "$name not found in archive"; rm -rf "$tmp"; return 1; }
  mv "$found" "$bin"; chmod +x "$bin"; rm -rf "$tmp"
  echo "$bin"
}

ensure_node() {
  fetch_binary "https://github.com/prometheus/node_exporter/releases/download/v${NODE_VERSION}/node_exporter-${NODE_VERSION}.${NODE_OS}-${NODE_ARCH}.tar.gz" node_exporter
}

ensure_nvidia() {
  fetch_binary "https://github.com/utkuozdemir/nvidia_gpu_exporter/releases/download/v${NVIDIA_VERSION}/nvidia_gpu_exporter_${NVIDIA_VERSION}_${NV_OS}_${NV_ARCH}.tar.gz" nvidia_gpu_exporter
}

start_one() { # $1 name  $2 binary  $3... args
  local name="$1"; shift; local bin="$1"; shift
  local pidf="$RUN/$name.pid"
  if [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null; then
    log "$name already running (pid $(cat "$pidf"))"; return
  fi
  nohup "$bin" "$@" >"$RUN/$name.log" 2>&1 &
  echo $! >"$pidf"
  sleep 0.5
  if kill -0 "$(cat "$pidf")" 2>/dev/null; then
    log "$name started (pid $(cat "$pidf"))"
  else
    warn "$name failed to start — see $RUN/$name.log"; tail -n 5 "$RUN/$name.log" || true
  fi
}

stop_one() { # $1 name
  local pidf="$RUN/$1.pid"
  [ -f "$pidf" ] || return
  local pid; pid="$(cat "$pidf")"
  kill "$pid" 2>/dev/null && log "$1 stopped (pid $pid)" || true
  rm -f "$pidf"
}

# Split out so the GPU exporter can be started on its own: the native macOS stack
# runs node_exporter under `brew services` and only needs this half.
cmd_nvidia() {
  if command -v nvidia-smi >/dev/null 2>&1; then
    start_one nvidia_gpu_exporter "$(ensure_nvidia)" "--web.listen-address=$NVIDIA_ADDR"
  else
    warn "nvidia-smi not found — skipping GPU exporter (the GPU dashboard row will be empty)"
    return 1
  fi
}

cmd_start() {
  if port_busy 9100; then
    log "port 9100 already served (containerised node-exporter?) — skipping node_exporter"
  else
    start_one node_exporter "$(ensure_node)" "--web.listen-address=$NODE_ADDR"
  fi
  cmd_nvidia || true
  echo
  log "done. Prometheus scrapes these at 127.0.0.1:9100 / :9835"
  log "verify:  curl -s localhost:9100/metrics | head   (and :9835 for GPU)"
}

cmd_stop()   { stop_one node_exporter; stop_one nvidia_gpu_exporter; }
cmd_status() {
  for n in node_exporter nvidia_gpu_exporter; do
    local pidf="$RUN/$n.pid"
    if [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null; then
      echo "$n: running (pid $(cat "$pidf"))"
    else echo "$n: stopped"; fi
  done
}

case "${1:-start}" in
  start)   cmd_start ;;
  nvidia)  cmd_nvidia ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  *) echo "usage: $0 [start|nvidia|stop|status|restart]" >&2; exit 2 ;;
esac
