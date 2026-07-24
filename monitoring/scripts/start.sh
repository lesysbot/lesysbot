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
    echo "✗ Docker is not installed. Install it first — see monitoring/README.md → Prerequisites." >&2
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

down() {
  case "$(uname -s)" in
    Linux)  dc -f docker-compose.linux.yml --profile gpu down; "$HERE/run-exporters.sh" stop 2>/dev/null || true ;;
    Darwin) dc down; "$HERE/run-exporters.sh" stop ;;
  esac
}

preflight
if [ "${1:-up}" = "down" ]; then down; echo "stack stopped."; exit 0; fi

case "$(uname -s)" in
  Linux)
    if command -v nvidia-smi >/dev/null 2>&1; then
      if has_nvidia_runtime; then
        echo "==> Linux + NVIDIA (container runtime): full stack on the host network"
        dc -f docker-compose.linux.yml --profile gpu up -d
      else
        echo "==> Linux + NVIDIA (no container toolkit): stack + native GPU exporter"
        dc -f docker-compose.linux.yml up -d
        "$HERE/run-exporters.sh" start      # starts only the GPU exporter (port 9100 is taken)
      fi
    else
      echo "==> Linux (no NVIDIA GPU detected): starting stack without GPU"
      dc -f docker-compose.linux.yml up -d
    fi
    ;;
  Darwin)
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
